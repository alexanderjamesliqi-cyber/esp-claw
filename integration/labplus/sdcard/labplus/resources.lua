-- Bounded, non-RPC diagnostics and admission control for shared hardware services.
local system=require('system')
local storage=require('storage')
local json=require('json')
local M={};local next_sample=0;local next_gc=0
function M.status()
 local heap=system.heap
 return {internal=heap.get_info(heap.caps.INTERNAL),psram=heap.get_info(heap.caps.SPIRAM),lua_kb=collectgarbage('count'),at_ms=system.millis()}
end
function M.admit()
 local info=M.status()
 return info.internal.free_size>=49152 and info.internal.largest_free_block>=16384 and info.psram.free_size>=4*1024*1024
end
function M.tick()
 local now=system.millis()
 if now>=next_gc then next_gc=now+500;collectgarbage('step',64) end
 if now<next_sample then return end;next_sample=now+5000
 storage.write_file('/sdcard/labplus/memory-status.json',json.encode(M.status()))
end
return M
