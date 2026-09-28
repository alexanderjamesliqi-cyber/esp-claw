/*
 * Minimal machine module platform stub for cap_mpy.
 *
 * Provides stubs for symbols referenced by ports/esp32/modmachine.c
 * that we don't implement (machine_rtc, machine_timer, machine_touchpad).
 */

#include "py/runtime.h"
#include "py/obj.h"
#include "esp_mac.h"

// ── FATFS stubs for functions not in ESP-IDF's fatfs ──────────────────
// MicroPython's vfs_fat.c uses f_getcwd/f_chdir which ESP-IDF's fatfs
// doesn't provide. Provide minimal stubs.
#include "ff.h"

FRESULT f_getcwd(char *buff, size_t len) {
    (void)buff;
    (void)len;
    return FR_OK;
}

FRESULT f_chdir(const char *path) {
    (void)path;
    return FR_OK;
}

#if MICROPY_PY_MACHINE

// ── Stubs for symbols referenced by the official port's modmachine.c ──
// These modules are not compiled in our build, but the module globals table
// in ports/esp32/modmachine.c references their types and config structs.

// machine_rtc stubs
#include "machine_rtc.h"
machine_rtc_config_t machine_rtc_config = {
    #if SOC_PM_SUPPORT_EXT0_WAKEUP
    .ext0_pin = -1,
    #endif
};

/* Never export zero-filled type objects: calling them can dereference NULL.
 * These peripherals are not owned/lifecycle-managed by the embedded VM. */
static mp_obj_t unavailable_make_new(const mp_obj_type_t *type, size_t n_args,
                                    size_t n_kw, const mp_obj_t *args)
{
    (void)type; (void)n_args; (void)n_kw; (void)args;
    mp_raise_NotImplementedError(MP_ERROR_TEXT("Peripheral unavailable in managed programs"));
}
MP_DEFINE_CONST_OBJ_TYPE(machine_rtc_type, MP_QSTR_RTC, MP_TYPE_FLAG_NONE,
    make_new, unavailable_make_new);

// machine_timer stubs
MP_DEFINE_CONST_OBJ_TYPE(machine_timer_type, MP_QSTR_Timer, MP_TYPE_FLAG_NONE,
    make_new, unavailable_make_new);

// machine_touchpad stubs
MP_DEFINE_CONST_OBJ_TYPE(machine_touchpad_type, MP_QSTR_TouchPad, MP_TYPE_FLAG_NONE,
    make_new, unavailable_make_new);

// ── Platform-specific machine functions ───────────────────────────────
// Note: mp_machine_reset, mp_machine_reset_cause, mp_machine_get_freq,
// mp_machine_set_freq, mp_machine_idle, mp_machine_unique_id,
// mp_machine_lightsleep, mp_machine_deepsleep are provided by
// ports/esp32/modmachine.c (included via MICROPY_PY_MACHINE_INCLUDEFILE).

#endif // MICROPY_PY_MACHINE
