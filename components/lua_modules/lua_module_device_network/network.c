#include <stdlib.h>
#include <string.h>
#include "lua.h"
#include "lauxlib.h"
#include "cap_lua.h"
#include "cap_mpy_network.h"
#include "esp_wifi.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "network.h"
#define MAX_APS 24
/* One device service, owned for the firmware lifetime; workers never access Lua. */
typedef struct {
    SemaphoreHandle_t lock;
    bool busy, connecting;
    esp_err_t result;
    uint32_t generation;
    int64_t scan_completed_us;
    uint16_t count;
    wifi_ap_record_t aps[MAX_APS];
    char ssid[33], password[64];
} network_service_t;
static network_service_t *service;
static void worker(void *arg)
{
    network_service_t *s=arg;
    esp_err_t err;
    uint16_t count=MAX_APS;
    wifi_ap_record_t *aps=NULL;
    if (s->connecting) {
        err=cap_mpy_network_connect(s->ssid,s->password,25000);
    } else {
        aps=calloc(MAX_APS,sizeof(*aps));
        /* Bound off-channel dwell while uploads/voice use the same radio.
         * Hosted firmware defaults can otherwise keep a scan active for >10s. */
        wifi_scan_config_t scan_config = {
            .scan_type = WIFI_SCAN_TYPE_ACTIVE,
            .scan_time = {.active = {.min = 20, .max = 60}, .passive = 60},
            .home_chan_dwell_time = 60,
        };
        err=aps ? esp_wifi_scan_start(&scan_config,true) : ESP_ERR_NO_MEM;
        if (err==ESP_OK) err=esp_wifi_scan_get_ap_records(&count,aps);
    }
    xSemaphoreTake(s->lock,portMAX_DELAY);
    if (err==ESP_OK && aps) { memcpy(s->aps,aps,count*sizeof(*aps));s->count=count;s->scan_completed_us=esp_timer_get_time(); }
    memset(s->password,0,sizeof(s->password));
    s->result=err;s->busy=false;
    xSemaphoreGive(s->lock);
    free(aps);vTaskDelete(NULL);
}
static int begin(lua_State *L,bool connecting)
{
    size_t ns=0,np=0;
    const char *ssid=connecting ? luaL_checklstring(L,1,&ns) : NULL;
    const char *pass=connecting ? luaL_checklstring(L,2,&np) : NULL;
    if (connecting) {
        luaL_argcheck(L,ns>0 && ns<=32 && strlen(ssid)==ns,1,"invalid SSID");
        luaL_argcheck(L,np<=63 && strlen(pass)==np,2,"invalid password");
    }
    network_service_t *s=service;
    xSemaphoreTake(s->lock,portMAX_DELAY);
    if (s->busy) { xSemaphoreGive(s->lock);lua_pushboolean(L,false);return 1; }
    /* Reopening settings reuses a recent result. Even explicit refresh has a
     * short cooldown, keeping repeated taps from monopolizing the radio. */
    if (!connecting && s->scan_completed_us) {
        int64_t age = esp_timer_get_time() - s->scan_completed_us;
        bool force = lua_toboolean(L, 1);
        if (age < (force ? 5000000LL : 30000000LL)) {
            xSemaphoreGive(s->lock);lua_pushboolean(L,true);return 1;
        }
    }
    s->busy=true;s->connecting=connecting;s->generation++;s->result=ESP_OK;
    if (connecting) { memcpy(s->ssid,ssid,ns+1);memcpy(s->password,pass,np+1); }
    else s->count=0;
    BaseType_t created=xTaskCreate(worker,"device_wifi",6144,s,4,NULL);
    if (created!=pdPASS) { s->busy=false;s->result=ESP_ERR_NO_MEM;memset(s->password,0,sizeof(s->password)); }
    xSemaphoreGive(s->lock);
    lua_pushboolean(L,created==pdPASS);return 1;
}
static int scan(lua_State *L){return begin(L,false);}
static int connect_wifi(lua_State *L){return begin(L,true);}
static int status(lua_State *L)
{
    cap_mpy_network_status_t current={0};
    cap_mpy_network_get_status(&current);
    lua_newtable(L);
    lua_pushboolean(L,current.connected);lua_setfield(L,-2,"connected");
    lua_pushstring(L,current.ssid);lua_setfield(L,-2,"ssid");
    lua_pushstring(L,current.ip);lua_setfield(L,-2,"ip");
    /* Copy under lock, then allocate Lua objects outside it (Lua errors longjmp). */
    network_service_t *snapshot=malloc(sizeof(*snapshot));
    if (!snapshot) return luaL_error(L,"network status allocation failed");
    xSemaphoreTake(service->lock,portMAX_DELAY);memcpy(snapshot,service,sizeof(*snapshot));
    memset(snapshot->password,0,sizeof(snapshot->password));xSemaphoreGive(service->lock);
    lua_pushboolean(L,snapshot->busy);lua_setfield(L,-2,"busy");
    lua_pushstring(L,snapshot->connecting ? "connect" : "scan");lua_setfield(L,-2,"operation");
    lua_pushinteger(L,snapshot->generation);lua_setfield(L,-2,"generation");
    lua_pushboolean(L,snapshot->result==ESP_OK);lua_setfield(L,-2,"ok");
    lua_newtable(L);
    for (int i=0;i<snapshot->count;i++) {
        wifi_ap_record_t *ap=&snapshot->aps[i];lua_newtable(L);
        lua_pushlstring(L,(char *)ap->ssid,strnlen((char *)ap->ssid,32));lua_setfield(L,-2,"ssid");
        lua_pushinteger(L,ap->rssi);lua_setfield(L,-2,"rssi");
        lua_pushboolean(L,ap->authmode!=WIFI_AUTH_OPEN);lua_setfield(L,-2,"secured");
        lua_rawseti(L,-2,i+1);
    }
    free(snapshot);lua_setfield(L,-2,"networks");return 1;
}
static int open_network(lua_State *L)
{
    const luaL_Reg api[]={{"scan",scan},{"connect",connect_wifi},{"status",status},{NULL,NULL}};
    lua_newtable(L);luaL_setfuncs(L,api,0);return 1;
}
esp_err_t lua_module_device_network_register(void)
{
    if (!service) {
        service=calloc(1,sizeof(*service));if (!service) return ESP_ERR_NO_MEM;
        service->lock=xSemaphoreCreateMutex();
        if (!service->lock) {free(service);service=NULL;return ESP_ERR_NO_MEM;}
    }
    return cap_lua_register_module("device_network",open_network);
}
