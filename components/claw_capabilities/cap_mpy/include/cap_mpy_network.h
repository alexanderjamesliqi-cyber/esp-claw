#pragma once
#include <stdbool.h>
#include <stdint.h>
#include "esp_err.h"
typedef struct { bool connected; char ssid[33]; char ip[16]; } cap_mpy_network_status_t;
typedef struct {
    esp_err_t (*connect)(const char *ssid, const char *password, uint32_t timeout_ms, void *ctx);
    void (*status)(cap_mpy_network_status_t *out, void *ctx);
    void *ctx;
} cap_mpy_network_provider_t;
/* Set once during boot, before any Python jobs start. Provider is copied. */
void cap_mpy_set_network_provider(const cap_mpy_network_provider_t *provider);

/* Shared provider entry points for the asynchronous on-device settings UI. */
esp_err_t cap_mpy_network_connect(const char *ssid,const char *password,uint32_t timeout_ms);
void cap_mpy_network_get_status(cap_mpy_network_status_t *status);
