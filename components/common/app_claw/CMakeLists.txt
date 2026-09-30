
set(app_claw_srcs
    "app_claw.c"
    "app_capabilities.c"
    "app_lua_modules.c"
)

if(CONFIG_APP_CLAW_ENABLE_CLI)
    list(APPEND app_claw_srcs "app_claw_cli.c" "app_claw_studio.c")
endif()

set(app_claw_private_requires console mbedtls claw_core spark_identity)
if(CONFIG_APP_CLAW_ENABLE_CLI AND CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG)
    list(APPEND app_claw_srcs "app_claw_usb_console.c")
    list(APPEND app_claw_private_requires esp_driver_usb_serial_jtag)
endif()

idf_component_register(
    SRCS
        ${app_claw_srcs}
    INCLUDE_DIRS
        "include"
    PRIV_REQUIRES
        ${app_claw_private_requires}
)

# IDF 5.x console uses fixed 256-byte defaults and exposes no buffer options.
# Override only driver installation, without editing IDF/vendor sources.
if(CONFIG_APP_CLAW_ENABLE_CLI AND CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG)
    target_link_options(${COMPONENT_LIB} INTERFACE "-Wl,--wrap=usb_serial_jtag_driver_install")
endif()
