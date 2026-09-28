idf_component_register(
    SRCS
        "src/lua_module_system.c"
    INCLUDE_DIRS
        "src"
    REQUIRES
        cap_lua
        esp_netif
        esp_timer
        esp_wifi
        freertos
        heap
)

if(CONFIG_SOC_USB_SERIAL_JTAG_SUPPORTED)
    idf_component_optional_requires(PRIVATE esp_driver_usb_serial_jtag)
endif()
