/* SPDX-License-Identifier: Apache-2.0 */
#include <stdlib.h>
#include <stdatomic.h>
#include <string.h>
#include "lua.h"
#include "lauxlib.h"
#include "cap_lua.h"
#include "esp_crt_bundle.h"
#include "esp_websocket_client.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#include "mbedtls/base64.h"
#include "lua_module_websocket.h"

#define WS_META "claw.websocket"
#define WS_MAX_MESSAGE (256 * 1024)
#define WS_QUEUE_LENGTH 128
#define WS_MAX_QUEUED_BYTES (4 * 1024 * 1024)
#define WS_WAIT_MS 10000
static _Atomic(lua_websocket_auth_provider_t) s_auth_provider;
void lua_module_websocket_set_auth_provider(lua_websocket_auth_provider_t provider)
{
    atomic_store(&s_auth_provider, provider);
}

typedef struct { char *data; size_t len; } ws_message_t;
typedef struct {
    esp_websocket_client_handle_t client;
    QueueHandle_t queue;
    QueueHandle_t outgoing;
    SemaphoreHandle_t sender_done;
    bool sender_started;
    atomic_bool closing;
    atomic_size_t outgoing_bytes;
    char *partial;
    size_t length;
    char *url;
    char *headers;
    lua_websocket_auth_provider_t auth_provider;
    atomic_bool connected;
    atomic_bool failed;
    atomic_size_t queued_bytes;
    atomic_int failure_reason;
} ws_object_t;

static void ws_fail(ws_object_t *w, int reason)
{
    atomic_store(&w->failure_reason, reason);
    atomic_store(&w->failed, true);
}
static const char *ws_failure(ws_object_t *w)
{
    switch (atomic_load(&w->failure_reason)) {
    case 2: return "WebSocket receive queue full";
    case 3: return "WebSocket message too large";
    case 4: return "WebSocket allocation failed";
    case 5: return "WebSocket peer closed";
    case 6: return "Factory device authorization unavailable";
    default: return "WebSocket disconnected";
    }
}
/* The ESP WebSocket task owns partial; the Lua task owns dequeued messages.
 * destroy joins the WebSocket task before freeing any callback state. */
static void ws_event(void *arg, esp_event_base_t base, int32_t id, void *raw)
{
    ws_object_t *w = arg;
    esp_websocket_event_data_t *e = raw;
    (void)base;
    if (id == WEBSOCKET_EVENT_CONNECTED) { w->connected = true; return; }
    if (id == WEBSOCKET_EVENT_DISCONNECTED || id == WEBSOCKET_EVENT_ERROR) {
        w->connected = false;
        ws_fail(w, 1);
        return;
    }
    if (id != WEBSOCKET_EVENT_DATA || w->failed) return;
    if (e->op_code == 8) { w->connected = false; ws_fail(w, 5); return; }
    if (e->op_code != 0 && e->op_code != 1 && e->op_code != 2) return;
    if (e->payload_offset == 0 && e->op_code != 0) {
        free(w->partial); w->partial = NULL; w->length = 0;
    }
    if (e->data_len < 0 || w->length + (size_t)e->data_len > WS_MAX_MESSAGE) {
        ws_fail(w, 3); return;
    }
    size_t needed = w->length + e->data_len;
    char *p = realloc(w->partial, needed + 1);
    if (!p) { ws_fail(w, 4); return; }
    w->partial = p;
    memcpy(p + w->length, e->data_ptr, e->data_len);
    w->length = needed;
    if (e->payload_offset + e->data_len == e->payload_len && e->fin) {
        ws_message_t message = { w->partial, w->length };
        w->partial = NULL; w->length = 0;
        size_t previous = atomic_fetch_add(&w->queued_bytes, message.len);
        if (previous + message.len > WS_MAX_QUEUED_BYTES ||
            xQueueSend(w->queue, &message, 0) != pdTRUE) {
            atomic_fetch_sub(&w->queued_bytes, message.len);
            free(message.data); ws_fail(w, 2);
        }
    }
}

static ws_object_t *ws_check(lua_State *L)
{
    ws_object_t **owner = luaL_checkudata(L, 1, WS_META);
    if (!*owner) luaL_error(L, "WebSocket closed");
    return *owner;
}

/* A client may take seconds to leave a network handshake. Its event callback
 * state is heap-owned until the cleanup worker joins it, never by a Lua VM. */
static QueueHandle_t s_cleanup_queue;
static atomic_uint s_live_clients;
#define WS_MAX_LIVE_CLIENTS 2

static void ws_sender(void *arg)
{
    ws_object_t *w = arg;
    /* Authentication may perform TLS. Keep it entirely off the Lua/UI task. */
    if (w->auth_provider) {
        if (w->auth_provider(w->url,w->headers,1024)!=ESP_OK) { ws_fail(w,6); goto finished; }
    }
    if (atomic_load(&w->closing)) goto finished;
    esp_websocket_client_config_t *cfg = calloc(1, sizeof(*cfg));
    if (!cfg) { ws_fail(w,4); goto finished; }
    cfg->uri=w->url;cfg->headers=w->headers;cfg->disable_auto_reconnect=true;
    cfg->crt_bundle_attach=esp_crt_bundle_attach;cfg->network_timeout_ms=WS_WAIT_MS;
    cfg->buffer_size=4096;cfg->task_stack=8192;
    w->client=esp_websocket_client_init(cfg);free(cfg);
    if (!w->client || esp_websocket_register_events(w->client,WEBSOCKET_EVENT_ANY,ws_event,w)!=ESP_OK ||
        esp_websocket_client_start(w->client)!=ESP_OK) { ws_fail(w,1); goto finished; }
    while (!atomic_load(&w->closing)) {
        ws_message_t message;
        if (xQueueReceive(w->outgoing, &message, pdMS_TO_TICKS(100)) != pdTRUE) continue;
        atomic_fetch_sub(&w->outgoing_bytes, message.len);
        if (!atomic_load(&w->closing) && !atomic_load(&w->failed)) {
            int sent = esp_websocket_client_send_text(w->client, message.data, message.len, pdMS_TO_TICKS(WS_WAIT_MS));
            if (sent != (int)message.len) ws_fail(w, 1);
        }
        free(message.data);
    }
finished:
    xSemaphoreGive(w->sender_done);
    vTaskDelete(NULL);
}

static void ws_destroy(ws_object_t *w)
{
    atomic_store(&w->closing, true);
    if (w->sender_started) xSemaphoreTake(w->sender_done, portMAX_DELAY);
    if (w->outgoing) {
        ws_message_t message;
        while (xQueueReceive(w->outgoing, &message, 0) == pdTRUE) free(message.data);
        vQueueDelete(w->outgoing);
    }
    if (w->sender_done) vSemaphoreDelete(w->sender_done);
    if (w->client) {
        esp_websocket_client_stop(w->client);
        esp_websocket_client_destroy(w->client);
        w->client = NULL;
    }
    if (w->queue) {
        ws_message_t message;
        while (xQueueReceive(w->queue, &message, 0) == pdTRUE) free(message.data);
        vQueueDelete(w->queue); w->queue = NULL;
    }
    free(w->partial); w->partial = NULL;
    free(w->url); w->url = NULL;
    free(w->headers); w->headers = NULL;
    w->connected = false;
    free(w);
    atomic_fetch_sub(&s_live_clients, 1);
}

static void ws_cleanup_worker(void *arg)
{
    (void)arg;
    for (;;) {
        ws_object_t *w = NULL;
        if (xQueueReceive(s_cleanup_queue, &w, portMAX_DELAY) == pdTRUE) ws_destroy(w);
    }
}

static int ws_close(lua_State *L)
{
    ws_object_t **owner = luaL_checkudata(L, 1, WS_META);
    if (!*owner) return 0;
    ws_object_t *w = *owner;
    /* Queue capacity covers every live client, including failed construction.
     * Detach immediately; callbacks cannot reference collected Lua userdata. */
    *owner = NULL;
    atomic_store(&w->closing, true);
    BaseType_t queued = xQueueSend(s_cleanup_queue, &w, 0);
    configASSERT(queued == pdTRUE);
    (void)queued;
    return 0;
}

static int ws_new(lua_State *L)
{
    luaL_checktype(L, 1, LUA_TTABLE);
    lua_getfield(L, 1, "url");
    const char *url = luaL_checkstring(L, -1);
    luaL_argcheck(L, strncmp(url, "wss://", 6) == 0, 1, "wss:// URL required");
    lua_getfield(L, 1, "headers");
    const char *headers = luaL_optstring(L, -1, "");
    lua_getfield(L, 1, "configured_auth");
    bool configured_auth = lua_toboolean(L, -1);
    lua_pop(L, 1);
    lua_websocket_auth_provider_t provider=configured_auth ? atomic_load(&s_auth_provider) : NULL;
    if(configured_auth && !provider)return luaL_error(L,"WebSocket authentication unavailable");
    ws_object_t **owner = lua_newuserdata(L, sizeof(*owner));
    *owner = NULL;
    luaL_setmetatable(L, WS_META);
    unsigned live = atomic_load(&s_live_clients);
    do {
        if (live >= WS_MAX_LIVE_CLIENTS) return luaL_error(L, "Previous WebSocket connections are still closing");
    } while (!atomic_compare_exchange_weak(&s_live_clients, &live, live + 1));
    ws_object_t *w = calloc(1, sizeof(*w));
    if (!w) {
        atomic_fetch_sub(&s_live_clients, 1);
        return luaL_error(L, "WebSocket allocation failed");
    }
    *owner = w;
    atomic_init(&w->closing, false);
    atomic_init(&w->outgoing_bytes, 0);
    atomic_init(&w->connected, false);
    atomic_init(&w->failed, false);
    atomic_init(&w->queued_bytes, 0);
    atomic_init(&w->failure_reason, 0);
    w->url = strdup(url);
    w->headers = configured_auth ? calloc(1,1024) : strdup(headers);
    w->auth_provider=provider;
    w->queue = xQueueCreate(WS_QUEUE_LENGTH, sizeof(ws_message_t));
    w->outgoing = xQueueCreate(32, sizeof(ws_message_t));
    w->sender_done = xSemaphoreCreateBinary();
    if (!w->url || !w->headers || !w->queue || !w->outgoing || !w->sender_done) return luaL_error(L, "WebSocket allocation failed");
    if (xTaskCreate(ws_sender, "ws_sender", 12288, w, 3, NULL) != pdPASS) return luaL_error(L, "WebSocket sender allocation failed");
    w->sender_started = true;
    return 1;
}

static int ws_send(lua_State *L)
{
    ws_object_t *w = ws_check(L);
    size_t n;
    const char *data = luaL_checklstring(L, 2, &n);
    luaL_argcheck(L, n <= WS_MAX_MESSAGE, 2, "message too large");
    if (!w->connected || w->failed) return luaL_error(L, "%s", ws_failure(w));
    if (atomic_load(&w->outgoing_bytes) + n > 512 * 1024) return luaL_error(L, "WebSocket send queue full");
    ws_message_t message = {malloc(n ? n : 1), n};
    if (!message.data) return luaL_error(L, "WebSocket send allocation failed");
    memcpy(message.data, data, n);
    atomic_fetch_add(&w->outgoing_bytes, n);
    if (xQueueSend(w->outgoing, &message, 0) != pdTRUE) {
        atomic_fetch_sub(&w->outgoing_bytes, n);
        free(message.data);
        return luaL_error(L, "WebSocket send queue full");
    }
    lua_pushboolean(L, 1); return 1;
}

static int ws_receive(lua_State *L)
{
    ws_object_t *w = ws_check(L);
    int wait = luaL_optinteger(L, 2, 0);
    luaL_argcheck(L, wait >= 0 && wait <= WS_WAIT_MS, 2, "timeout outside 0..10000");
    if (!w->queue) return luaL_error(L, "WebSocket closed");
    ws_message_t message;
    if (xQueueReceive(w->queue, &message, pdMS_TO_TICKS(wait)) == pdTRUE) {
        atomic_fetch_sub(&w->queued_bytes, message.len);
        lua_pushlstring(L, message.data, message.len);
        free(message.data); return 1;
    }
    if (w->failed) return luaL_error(L, "%s", ws_failure(w));
    lua_pushnil(L); return 1;
}

static int ws_base64(lua_State *L, bool decode)
{
    size_t n, written = 0;
    const unsigned char *data = (const unsigned char *)luaL_checklstring(L, 1, &n);
    luaL_argcheck(L, n <= WS_MAX_MESSAGE, 1, "buffer too large");
    size_t size = decode ? n + 1 : ((n + 2) / 3) * 4 + 1;
    unsigned char *out = malloc(size);
    if (!out) return luaL_error(L, "base64 allocation failed");
    int ret = decode ? mbedtls_base64_decode(out, size, &written, data, n) :
                       mbedtls_base64_encode(out, size, &written, data, n);
    if (ret) { free(out); return luaL_error(L, "invalid base64 input"); }
    lua_pushlstring(L, (const char *)out, written);
    free(out); return 1;
}
static int ws_encode(lua_State *L) { return ws_base64(L, false); }
static int ws_decode(lua_State *L) { return ws_base64(L, true); }

static int luaopen_websocket(lua_State *L)
{
    static const luaL_Reg methods[] = {
        {"send", ws_send}, {"receive", ws_receive}, {"close", ws_close}, {NULL, NULL}
    };
    if (luaL_newmetatable(L, WS_META)) {
        lua_pushcfunction(L, ws_close); lua_setfield(L, -2, "__gc");
        lua_newtable(L); luaL_setfuncs(L, methods, 0); lua_setfield(L, -2, "__index");
    }
    lua_pop(L, 1);
    static const luaL_Reg module[] = {
        {"new", ws_new}, {"base64_encode", ws_encode}, {"base64_decode", ws_decode}, {NULL, NULL}
    };
    lua_newtable(L); luaL_setfuncs(L, module, 0); return 1;
}
esp_err_t lua_module_websocket_register(void)
{
    if (!s_cleanup_queue) {
        s_cleanup_queue = xQueueCreate(WS_MAX_LIVE_CLIENTS, sizeof(ws_object_t *));
        if (!s_cleanup_queue) return ESP_ERR_NO_MEM;
        if (xTaskCreate(ws_cleanup_worker, "ws_cleanup", 4096, NULL, 3, NULL) != pdPASS) {
            vQueueDelete(s_cleanup_queue);s_cleanup_queue = NULL;
            return ESP_ERR_NO_MEM;
        }
    }
    return cap_lua_register_module("websocket", luaopen_websocket);
}
