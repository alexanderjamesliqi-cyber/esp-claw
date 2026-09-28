-- Antialiased Noto Sans SC + Roboto Mono, streamed from SD with bounded caches.
local display=require('display')
local json=require('json')
local root='/sdcard/labplus/'

local ranges={{32,126},{0x2000,0x206f},{0x3000,0x30ff},{0x3400,0x9fff},{0xff00,0xffef}}
local cache,cache_keys,cache_next={},{},1
-- A full page contains ~306 glyphs plus chrome. Evict one entry at a time,
-- never the whole visible page; RGB565 cache stays below ~1 MiB in PSRAM.
local CACHE_LIMIT=512
local heading_index=nil
local index_file=io.open(root..'fonts/heading.json','rb')
if index_file then heading_index=json.decode(index_file:read('*a'));index_file:close() end
local M={}
local function offset(cp)
 local n=0
 for _,r in ipairs(ranges) do if cp>=r[1] and cp<=r[2] then return n+cp-r[1] end;n=n+r[2]-r[1]+1 end
 return nil
end
local function open_font(name,batch)
 if batch.name~=name then
  if batch.file then batch.file:close();batch.file=nil end
  batch.name=name;batch.file=io.open(root..name,'rb')
 end
 return batch.file
end
local function palette(fg,bg)
 local f=tonumber(fg:sub(2),16);local b=tonumber(bg:sub(2),16);local result={}
 for alpha=0,15 do
  local r=(((f>>16)&255)*alpha+((b>>16)&255)*(15-alpha))//15
  local g=(((f>>8)&255)*alpha+((b>>8)&255)*(15-alpha))//15
  local blue=((f&255)*alpha+(b&255)*(15-alpha))//15
  local rgb=(r>>3)<<11 | (g>>2)<<5 | (blue>>3)
  result[alpha]=string.char(rgb&255,(rgb>>8)&255)
 end
 return result
end
local function pixels(cp,fg,bg,heading,batch)
 local key=tostring(cp)..fg..bg..tostring(heading)
 if cache[key] then return cache[key][1],cache[key][2] end
 local n=offset(cp);local size=24;local font;local raw
 if (heading or not n) and heading_index and heading_index[tostring(cp)] then
  font=open_font('fonts/heading.bin',batch);size=32;n=heading_index[tostring(cp)]
  if font then font:seek('set',n*512);raw=font:read(512) end
 else
  n=n or (63-32)
  font=open_font(string.format('fonts/body-%02d.bin',n//1024),batch)
  if font then font:seek('set',(n%1024)*288);raw=font:read(288) end
 end
 local colors=palette(fg,bg);local p={}
 if raw then
  for i=1,#raw do local byte=raw:byte(i);p[#p+1]=colors[byte>>4];p[#p+1]=colors[byte&15] end
 else
  size=24;local fallback=assert(open_font('font24.bin',batch));fallback:seek('set',(offset(cp) or (63-32))*72);raw=assert(fallback:read(72))
  for i=1,72 do local byte=raw:byte(i);for bit=7,0,-1 do p[#p+1]=colors[(byte&(1<<bit))~=0 and 15 or 0] end end
 end
 local result=table.concat(p)
 local old=cache_keys[cache_next];if old then cache[old]=nil end
 cache_keys[cache_next]=key;cache_next=cache_next%CACHE_LIMIT+1
 cache[key]={result,size};return result,size
end
function M.lines(value,width)
 local lines,line,used={},{},0
 for _,cp in utf8.codes(value:gsub('\r',''):gsub('\t','    ')) do
  local advance=cp<128 and 12 or 24
  if cp==10 then lines[#lines+1]=line;line={};used=0
  else
   if used+advance>width then lines[#lines+1]=line;line={};used=0 end
   line[#line+1]=cp;used=used+advance
  end
 end
 if #line>0 or #lines==0 then lines[#lines+1]=line end
 return lines
end
function M.draw_line(x,y,line,style)
 style=style or {};local size=style.size or 24
 -- Share one font descriptor within a line; close even on rendering errors.
 local batch={}
 local ok,err=pcall(function()
 for _,cp in ipairs(line) do
  local data,source_size=pixels(cp,style.color or '#172B4D',style.bg or '#FFFFFF',size>=30,batch)
  display.draw_pixels(x,y,data,{format='rgb565',width=source_size,height=source_size,mode='stretch',dst_width=size,dst_height=size})
  x=x+(cp<128 and size//2 or size)
 end
 end)
 if batch.file then batch.file:close() end
 if not ok then error(err,0) end
end
return M
