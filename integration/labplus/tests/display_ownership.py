from pathlib import Path
import subprocess,tempfile
root=Path(__file__).resolve().parents[3]
s=(root/'components/lua_modules/lua_module_display/src/lua_module_display.c').read_text()
a=s.index('static void lua_display_exit_cleanup(');b=s.index('static int lua_display_init(',a)
source='''#include <stdbool.h>
#include <stddef.h>
#include <assert.h>
typedef struct {int x;} lua_State;
typedef int esp_err_t;
#define ESP_OK 0
#define ESP_LOGI(...) ((void)0)
#define ESP_LOGW(...) ((void)0)
static bool s_display_active;
static lua_State *s_display_owner;
static void *s_display_session;
static int destroyed,closed;
static int display_hal_destroy(void){destroyed++;return 0;}
static int display_service_close(void *p){assert(p);closed++;return 0;}
'''+s[a:b]+'''
int main(void){
 lua_State owner={0},other={0};s_display_active=true;s_display_owner=&owner;s_display_session=&owner;
 lua_display_exit_cleanup(&other);assert(s_display_active && destroyed==0 && closed==0);
 lua_display_exit_cleanup(&owner);assert(!s_display_active && !s_display_owner && destroyed==1 && closed==1);
 lua_display_exit_cleanup(&owner);assert(destroyed==1 && closed==1);return 0;
}
'''
with tempfile.TemporaryDirectory() as d:
 p=Path(d)/'test.c';p.write_text(source);exe=Path(d)/'test'
 subprocess.run(['cc','-Wall','-Werror','-fsanitize=undefined',str(p),'-o',str(exe)],check=True);subprocess.run([str(exe)],check=True)
print('PASS: actual display cleanup ignores unrelated VM, releases only its owner once')
