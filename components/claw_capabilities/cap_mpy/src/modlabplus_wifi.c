/* SPDX-License-Identifier: Apache-2.0 */
#include <string.h>
#include "py/runtime.h"
#include "py/mpthread.h"
#include "cap_mpy_network.h"
#include "cap_mpy.h"
static cap_mpy_network_provider_t provider;
void cap_mpy_set_network_provider(const cap_mpy_network_provider_t *p) { provider = *p; }
esp_err_t cap_mpy_network_connect(const char *ssid,const char *password,uint32_t timeout_ms)
{
    return provider.connect ? provider.connect(ssid,password,timeout_ms,provider.ctx) : ESP_ERR_INVALID_STATE;
}
void cap_mpy_network_get_status(cap_mpy_network_status_t *out)
{
    memset(out,0,sizeof(*out));
    if (provider.status) provider.status(out,provider.ctx);
}
static mp_obj_t wifi_connect(size_t n_args, const mp_obj_t *args, mp_map_t *kwargs)
{
    enum { SSID, PASSWORD, TIMEOUT };
    static const mp_arg_t allowed[] = {
        { MP_QSTR_ssid, MP_ARG_REQUIRED | MP_ARG_OBJ, {.u_obj = MP_OBJ_NULL} },
        { MP_QSTR_password, MP_ARG_REQUIRED | MP_ARG_OBJ, {.u_obj = MP_OBJ_NULL} },
        { MP_QSTR_timeout_ms, MP_ARG_INT, {.u_int = 30000} },
    };
    mp_arg_val_t values[3];
    mp_arg_parse_all(n_args, args, kwargs, 3, allowed, values);
    const char *ssid = mp_obj_str_get_str(values[SSID].u_obj);
    const char *password = mp_obj_str_get_str(values[PASSWORD].u_obj);
    int timeout = values[TIMEOUT].u_int;
    if (!strlen(ssid) || strlen(ssid) > 32 || strlen(password) > 63 || timeout < 1000 || timeout > 60000)
        mp_raise_ValueError(MP_ERROR_TEXT("invalid Wi-Fi credentials length or timeout"));
    if (!provider.connect) mp_raise_msg(&mp_type_RuntimeError, MP_ERROR_TEXT("Wi-Fi service unavailable"));
    MP_THREAD_GIL_EXIT();
    esp_err_t err = provider.connect(ssid, password, timeout, provider.ctx);
    MP_THREAD_GIL_ENTER();
    cap_mpy_poll_hook();
    if (err != ESP_OK)
        mp_raise_msg_varg(&mp_type_OSError, MP_ERROR_TEXT("Wi-Fi connect/save failed: %s; previous config retained"), esp_err_to_name(err));
    return mp_const_true;
}
static MP_DEFINE_CONST_FUN_OBJ_KW(wifi_connect_obj, 2, wifi_connect);
static mp_obj_t wifi_status(void)
{
    cap_mpy_network_status_t status = {0};
    if (provider.status) provider.status(&status, provider.ctx);
    mp_obj_t out = mp_obj_new_dict(3);
    mp_obj_dict_store(out, MP_OBJ_NEW_QSTR(MP_QSTR_connected), mp_obj_new_bool(status.connected));
    mp_obj_dict_store(out, MP_OBJ_NEW_QSTR(MP_QSTR_ssid), mp_obj_new_str(status.ssid, strlen(status.ssid)));
    mp_obj_dict_store(out, MP_OBJ_NEW_QSTR(MP_QSTR_ip), mp_obj_new_str(status.ip, strlen(status.ip)));
    return out;
}
static MP_DEFINE_CONST_FUN_OBJ_0(wifi_status_obj, wifi_status);
static const mp_rom_map_elem_t globals_table[] = {
    { MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR_labplus_wifi) },
    { MP_ROM_QSTR(MP_QSTR_connect), MP_ROM_PTR(&wifi_connect_obj) },
    { MP_ROM_QSTR(MP_QSTR_status), MP_ROM_PTR(&wifi_status_obj) },
};
static MP_DEFINE_CONST_DICT(globals, globals_table);
const mp_obj_module_t labplus_wifi_module = { .base = {&mp_type_module}, .globals = (mp_obj_dict_t *)&globals };
MP_REGISTER_MODULE(MP_QSTR_labplus_wifi, labplus_wifi_module);
