"""Exercise actual C registry beyond the former 32-slot limit and at capacity."""
from pathlib import Path
import re, subprocess, tempfile
root=Path(__file__).resolve().parents[3]
source=(root/'components/claw_capabilities/cap_lua/src/cap_lua.c').read_text()
header=(root/'components/claw_capabilities/cap_lua/src/cap_lua_internal.h').read_text()
limit=int(re.search(r'#define CAP_LUA_MAX_MODULES\s+(\d+)',header)[1])
start=source.index('esp_err_t cap_lua_register_module(')
end=source.index('\nesp_err_t cap_lua_register_modules(',start)
c='''#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
typedef int esp_err_t;
typedef int (*lua_CFunction)(void *);
#define ESP_OK 0
#define ESP_ERR_INVALID_ARG 1
#define ESP_ERR_INVALID_STATE 2
#define ESP_ERR_NO_MEM 3
#define ESP_LOGE(...) ((void)0)
#define CAP_LUA_MAX_MODULES LIMIT
static struct {const char *name; lua_CFunction open_fn;} s_modules[CAP_LUA_MAX_MODULES];
static size_t s_module_count;
static bool s_module_registration_locked;
'''.replace('LIMIT',str(limit))+source[start:end]+'''
static int opener(void *x) {return 0;}
int main(void) {
 char names[CAP_LUA_MAX_MODULES+1][24];
 assert(cap_lua_register_module(NULL,opener)==ESP_ERR_INVALID_ARG);
 for (int i=0;i<CAP_LUA_MAX_MODULES+1;i++) snprintf(names[i],24,"driver_%d",i);
 for (int i=0;i<33;i++) assert(cap_lua_register_module(names[i],opener)==ESP_OK);
 assert(cap_lua_register_module(names[0],opener)==ESP_ERR_INVALID_STATE);
 for (int i=33;i<CAP_LUA_MAX_MODULES;i++) assert(cap_lua_register_module(names[i],opener)==ESP_OK);
 assert(cap_lua_register_module(names[CAP_LUA_MAX_MODULES],opener)==ESP_ERR_NO_MEM);
 assert(s_module_count==CAP_LUA_MAX_MODULES);
 puts("PASS: 33-module boot regression, duplicates and capacity guard");
}
'''
with tempfile.TemporaryDirectory() as tmp:
 p=Path(tmp);(p/'registry.c').write_text(c)
 subprocess.run(['clang','-fsanitize=undefined',str(p/'registry.c'),'-o',str(p/'registry')],check=True)
 subprocess.run([str(p/'registry')],check=True)
