local M={PROGRAM_BYTES=16384,TEXT_BYTES=8192,LIBRARY_ITEMS=128}
function M.text(value)
 value=tostring(value or '')
 if #value<=M.TEXT_BYTES then return value end
 local finish=M.TEXT_BYTES
 while finish>0 and value:byte(finish+1)>=128 and value:byte(finish+1)<192 do finish=finish-1 end
 return value:sub(1,finish)..'\n内容较长，仅显示前半部分。'
end
function M.read_program(path)
 local file=assert(io.open(path,'rb'),'program unavailable')
 local size=file:seek('end');file:seek('set',0)
 if not size or size>M.PROGRAM_BYTES then file:close();error('program exceeds 16 KiB') end
 local source=file:read('*a');file:close();return source
end
return M
