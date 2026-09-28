/* SPDX-License-Identifier: Apache-2.0 */
#include "audio_private.h"
#define CONVERTER_META "audio.stream_converter"
typedef struct { audio_converter_t converter; bool opened; } stream_converter_t;
static int converter_close(lua_State *L)
{
    stream_converter_t *c = luaL_checkudata(L, 1, CONVERTER_META);
    if (c->opened) { audio_converter_destroy(&c->converter); c->opened = false; }
    return 0;
}
static int converter_process(lua_State *L)
{
    stream_converter_t *c = luaL_checkudata(L, 1, CONVERTER_META);
    size_t length;
    const uint8_t *data = (const uint8_t *)luaL_checklstring(L, 2, &length);
    luaL_argcheck(L, c->opened, 1, "converter closed");
    luaL_argcheck(L, length <= 256 * 1024, 2, "PCM block too large");
    if (!length) { lua_pushliteral(L, ""); return 1; }
    uint8_t *out = NULL;
    uint32_t out_length = 0;
    esp_err_t err = audio_converter_process(&c->converter, data, length, &out, &out_length);
    if (err != ESP_OK) return luaL_error(L, "PCM conversion failed: %s", esp_err_to_name(err));
    lua_pushlstring(L, (const char *)out, out_length);
    return 1;
}
int lua_audio_stream_converter(lua_State *L)
{
    audio_format_t src = {0}, dst = {0};
    luaL_checktype(L, 1, LUA_TTABLE); luaL_checktype(L, 2, LUA_TTABLE);
    lua_audio_parse_format_table(L, 1, &src, false);
    lua_audio_parse_format_table(L, 2, &dst, false);
    if (audio_format_complete(&src) != ESP_OK || audio_format_complete(&dst) != ESP_OK)
        return luaL_error(L, "Invalid PCM format");
    if (luaL_newmetatable(L, CONVERTER_META)) {
        lua_pushcfunction(L, converter_close); lua_setfield(L, -2, "__gc");
        lua_newtable(L);
        lua_pushcfunction(L, converter_close); lua_setfield(L, -2, "close");
        lua_pushcfunction(L, converter_process); lua_setfield(L, -2, "process");
        lua_setfield(L, -2, "__index");
    }
    lua_pop(L, 1);
    stream_converter_t *c = lua_newuserdata(L, sizeof(*c));
    memset(c, 0, sizeof(*c)); luaL_setmetatable(L, CONVERTER_META);
    esp_err_t err = audio_converter_create(&c->converter, &src, &dst);
    if (err != ESP_OK) {
        audio_converter_destroy(&c->converter);
        return luaL_error(L, "PCM converter creation failed: %s", esp_err_to_name(err));
    }
    c->opened = true;
    return 1;
}
