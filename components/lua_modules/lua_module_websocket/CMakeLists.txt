idf_component_register(SRCS "src/lua_module_websocket.c" INCLUDE_DIRS "src"
    REQUIRES cap_lua esp_websocket_client mbedtls esp-tls freertos)
