local live,peak,opens=0,0,0
io.open=function(path,mode)
 live=live+1;opens=opens+1;peak=math.max(peak,live)
 local closed=false
 return {seek=function()end,read=function(_,size)return size=='*a' and '{}' or string.rep('\255',size)end,
 close=function()assert(not closed);closed=true;live=live-1 end}
end
package.preload.json=function()return {decode=function()return {['183']=0} end}end
package.preload.display=function()return {draw_pixels=function()end}end
local M=dofile(TEXT_PATH)
for cp=0x4e00,0x4e00+255 do M.draw_line(0,0,{cp},{color='#172B4D',bg='#F3F6FC'}) end
M.draw_line(0,0,{183})
assert(live==0 and peak==1 and opens>256)
print('PASS: antialiased font stress closes every SD file; peak one font descriptor and no retained handles')

-- Repainting a whole page must not clear/reload the cache on every frame.
for cp=0x5100,0x5100+319 do M.draw_line(0,0,{cp}) end
local before=opens
for cp=0x5100,0x5100+319 do M.draw_line(0,0,{cp}) end
assert(opens==before,'full-page repaint reread SD fonts')
assert(live==0 and peak==1)
print('PASS: complete 320-glyph page repaint uses cached pixels, zero SD reads')

local row={};for cp=0x6000,0x6011 do row[#row+1]=cp end
local before=opens;M.draw_line(0,0,row)
assert(opens==before+1 and live==0,'glyphs on one line must share one transient file')
require('display').draw_pixels=function()error('injected display failure')end
assert(not pcall(M.draw_line,0,0,{0x7000}))
assert(live==0,'rendering failure leaked a font descriptor')
print('PASS: one transient font descriptor per line, closed even on rendering failure')
