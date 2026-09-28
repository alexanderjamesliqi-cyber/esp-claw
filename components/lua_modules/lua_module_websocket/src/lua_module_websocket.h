#pragma once
#include <stddef.h>
#include "esp_err.h"
typedef esp_err_t (*lua_websocket_auth_provider_t)(const char *url, char *headers, size_t size);
void lua_module_websocket_set_auth_provider(lua_websocket_auth_provider_t provider);
esp_err_t lua_module_websocket_register(void);
