#include <stdlib.h>
#include <string.h>
#include "lua.h"
#include "lauxlib.h"
#include "cap_lua.h"
#include "cap_mpy.h"
#include "runner.h"
#define RESULT_SIZE 4096
static int invoke(lua_State *L, int action)
{
    char *result=calloc(1,RESULT_SIZE);
    if (!result) return luaL_error(L,"runner allocation failed");
    esp_err_t err;
    if (action==0) err=cap_mpy_run_script_async("/sdcard/labplus/generated_runner.py",NULL,lua_toboolean(L,1) ? 0 : 60000,
        "ui_program","ui_program",false,result,RESULT_SIZE);
    else if (action==1) err=cap_mpy_stop_job("ui_program",0,result,RESULT_SIZE);
    else err=cap_mpy_list_jobs("all",result,RESULT_SIZE);
    lua_pushboolean(L,err==ESP_OK);lua_pushstring(L,result);free(result);return 2;
}
static int start(lua_State *L){return invoke(L,0);}
static int stop(lua_State *L){return invoke(L,1);}
static int jobs(lua_State *L){return invoke(L,2);}
static int validate(lua_State *L)
{
    const char *path=luaL_checkstring(L,1);
    luaL_argcheck(L,strncmp(path,"/sdcard/programs/",17)==0 && !strstr(path,".."),1,"program path required");
    char *result=calloc(1,RESULT_SIZE);
    if (!result) return luaL_error(L,"validation allocation failed");
    esp_err_t err=cap_mpy_validate_script(path,result,RESULT_SIZE);
    lua_pushboolean(L,err==ESP_OK);lua_pushstring(L,result);
    lua_pushboolean(L,err==ESP_ERR_INVALID_STATE);free(result);return 3;
}
static int open_runner(lua_State *L)
{
    static const luaL_Reg api[]={{"start",start},{"stop",stop},{"jobs",jobs},{"validate",validate},{NULL,NULL}};
    lua_newtable(L);luaL_setfuncs(L,api,0);return 1;
}
esp_err_t lua_module_micropython_runner_register(void)
{
    return cap_lua_register_module("micropython_runner",open_runner);
}
