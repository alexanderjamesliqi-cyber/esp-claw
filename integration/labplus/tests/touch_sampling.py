"""Compile the actual sampling function against a consuming-cache driver fake."""
from pathlib import Path
import subprocess, tempfile
repo=Path(__file__).resolve().parents[3]
s=(repo/'components/lua_modules/lua_module_lcd_touch/src/lua_module_lcd_touch.c').read_text()
start=s.index('static esp_err_t lua_lcd_touch_read_raw(')
end=s.index('\nstatic ',start+10)
function=s[start:end]
preamble=r'''
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <assert.h>
typedef int esp_err_t;
#define ESP_OK 0
#define ESP_ERR_INVALID_ARG 1
typedef struct {uint16_t x,y;} esp_lcd_touch_point_data_t;
typedef struct {struct {void *interrupt_callback;} config;bool finger,cache;int reads,error;} device;
typedef device *esp_lcd_touch_handle_t;
static bool locked;static int lock_error;
static bool display_service_is_started(void){return true;}
static int display_service_lock(void){if(lock_error)return lock_error;assert(!locked);locked=true;return 0;}
static void display_service_unlock(void){assert(locked);locked=false;}
static int esp_lcd_touch_read_data(device *d){d->reads++;d->cache=d->finger;return d->error;}
static int esp_lcd_touch_get_data(device *d,esp_lcd_touch_point_data_t *p,uint8_t *n,int max){if(!locked)d->cache=false;*n=d->cache;p->x=240;p->y=780;d->cache=false;return 0;}
'''
main=r'''
int main(void){
 device d={.config={.interrupt_callback=(void*)1},.finger=true};bool down;uint16_t x,y;
 for(int i=0;i<20;i++){assert(lua_lcd_touch_read_raw(&d,&down,&x,&y)==0);assert(down&&x==240&&y==780);}
 d.finger=false;assert(lua_lcd_touch_read_raw(&d,&down,&x,&y)==0);assert(!down);
 d.error=42;assert(lua_lcd_touch_read_raw(&d,&down,&x,&y)==42);
 assert(!locked);assert(d.reads==22);lock_error=7;assert(lua_lcd_touch_read_raw(&d,&down,&x,&y)==7);assert(!locked);return 0;
}
'''
with tempfile.TemporaryDirectory() as t:
 p=Path(t);(p/'test.c').write_text(preamble+function+main)
 subprocess.run(['clang','-std=c11',str(p/'test.c'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True)
print('PASS: 20 held samples with competing LVGL cache reader, release, I2C and lock failures')
