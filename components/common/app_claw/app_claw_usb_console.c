/* Keep USB uploads reliable during SD/network/audio work. The IDF console
 * installs the driver with 256-byte rings; RX overflow is silently discarded.
 * The application supplies bounded rings before the driver/ISR are started.
 * This is linked only when the USB Serial/JTAG console is selected. */
#include "driver/usb_serial_jtag.h"
#include "esp_log.h"

#define APP_CLAW_USB_RX_BYTES 4096
#define APP_CLAW_USB_TX_BYTES 4096

/* Explicit anchor: --wrap references from another static archive alone do not
 * reliably extract this object on all linker orders. */
void app_claw_usb_console_link(void) {}

esp_err_t __real_usb_serial_jtag_driver_install(usb_serial_jtag_driver_config_t *config);
esp_err_t __wrap_usb_serial_jtag_driver_install(usb_serial_jtag_driver_config_t *config)
{
    if (!config) return ESP_ERR_INVALID_ARG;
    usb_serial_jtag_driver_config_t buffered=*config;
    if (buffered.rx_buffer_size<APP_CLAW_USB_RX_BYTES) buffered.rx_buffer_size=APP_CLAW_USB_RX_BYTES;
    if (buffered.tx_buffer_size<APP_CLAW_USB_TX_BYTES) buffered.tx_buffer_size=APP_CLAW_USB_TX_BYTES;
    ESP_LOGI("app_claw_usb", "Console rings: RX %lu, TX %lu bytes",(unsigned long)buffered.rx_buffer_size,(unsigned long)buffered.tx_buffer_size);
    return __real_usb_serial_jtag_driver_install(&buffered);
}
