local internal={free_size=96000,largest_free_block=32000};local psram={free_size=20000000}
package.preload.system=function()return {millis=function()return 1 end,heap={caps={INTERNAL=2048,SPIRAM=1024},get_info=function(cap)assert(cap);return cap==2048 and internal or psram end}}end
package.preload.storage=function()return {write_file=function()end}end
package.preload.json=function()return {encode=function(v)return v end}end
local M=dofile(RESOURCE_PATH)
assert(M.admit());internal.free_size=40000;assert(not M.admit())
internal.free_size=96000;internal.largest_free_block=12000;assert(not M.admit())
internal.largest_free_block=32000;psram.free_size=3000000;assert(not M.admit())
psram.free_size=20000000;assert(M.admit());M.tick()
print('PASS: admission checks correct RAM capabilities, free bytes, largest internal block and PSRAM reserve')
