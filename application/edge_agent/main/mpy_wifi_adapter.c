/* SPDX-License-Identifier: Apache-2.0 */
#include "sdkconfig.h"
#if CONFIG_APP_CLAW_CAP_MPY
#include <stdlib.h>
#include <string.h>
#include "app_config.h"
#include "cap_mpy_network.h"
#include "cap_mpy.h"
#include "esp_timer.h"
#include "wifi_manager.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
typedef struct { SemaphoreHandle_t lock; } wifi_adapter_t;
static wifi_adapter_t adapter;
static esp_err_t apply(const app_config_t *cfg)
{
    wifi_manager_config_t net = {
        .sta_ssid=cfg->wifi_ssid, .sta_password=cfg->wifi_password,
        .ap_ssid=cfg->ap_ssid[0] ? cfg->ap_ssid : NULL,
        .ap_password=cfg->ap_password[0] ? cfg->ap_password : NULL,
        .ap_behavior=cfg->ap_behavior,
    };
    return wifi_manager_apply_sta_config(&net);
}
static esp_err_t connect_saved(const char *ssid, const char *password, uint32_t timeout, void *ctx)
{
    wifi_adapter_t *a=ctx;
    if (xSemaphoreTake(a->lock, 0)!=pdTRUE) return ESP_ERR_INVALID_STATE;
    app_config_t *old=calloc(1,sizeof(*old)), *candidate=calloc(1,sizeof(*candidate));
    esp_err_t err=ESP_ERR_NO_MEM;
    bool applied=false;
    if (!old || !candidate) goto done;
    err=app_config_load(old); if (err!=ESP_OK) goto done;
    memcpy(candidate,old,sizeof(*candidate));
    strlcpy(candidate->wifi_ssid,ssid,sizeof(candidate->wifi_ssid));
    strlcpy(candidate->wifi_password,password,sizeof(candidate->wifi_password));
    err=app_config_validate_wifi(candidate,NULL); if (err!=ESP_OK) goto done;
    applied=true;
    err=apply(candidate); if (err!=ESP_OK) goto done;
    int64_t until=esp_timer_get_time()+(int64_t)timeout*1000;
    do {
        if (cap_mpy_cancel_pending()) {err=ESP_ERR_TIMEOUT;goto done;}
        err=wifi_manager_wait_connected(100);
    } while (err==ESP_ERR_TIMEOUT && esp_timer_get_time()<until);
    if (err!=ESP_OK) goto done;
    if (cap_mpy_cancel_pending()) {err=ESP_ERR_TIMEOUT;goto done;}
    /* Reload current settings so an unrelated LLM setting change isn't overwritten. */
    err=app_config_load(candidate); if (err!=ESP_OK) goto done;
    strlcpy(candidate->wifi_ssid,ssid,sizeof(candidate->wifi_ssid));
    strlcpy(candidate->wifi_password,password,sizeof(candidate->wifi_password));
    err=app_config_save(candidate);
done:
    if (err!=ESP_OK && applied) apply(old);
    if (old) { memset(old,0,sizeof(*old)); free(old); }
    if (candidate) { memset(candidate,0,sizeof(*candidate)); free(candidate); }
    xSemaphoreGive(a->lock);
    return err;
}
static void get_status(cap_mpy_network_status_t *out, void *ctx)
{
    (void)ctx;
    wifi_manager_status_t status={0};
    wifi_manager_get_status(&status);
    out->connected=status.sta_connected;
    strlcpy(out->ip,status.sta_ip ? status.sta_ip : "0.0.0.0",sizeof(out->ip));
    /* UI polling must never wait for hosted C5 RPC replies. */
    if (status.sta_connected && status.sta_ssid)
        strlcpy(out->ssid,status.sta_ssid,sizeof(out->ssid));
}
void app_mpy_wifi_adapter_init(void)
{
    adapter.lock=xSemaphoreCreateMutex();
    ESP_ERROR_CHECK(adapter.lock ? ESP_OK : ESP_ERR_NO_MEM);
    const cap_mpy_network_provider_t provider={connect_saved,get_status,&adapter};
    cap_mpy_set_network_provider(&provider);
}
#else
void app_mpy_wifi_adapter_init(void) {}
#endif
