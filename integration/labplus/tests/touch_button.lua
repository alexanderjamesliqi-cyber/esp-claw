local now=3000
local sample={pressed=false};local presses,releases=0,0
local storage={join_path=function(a,b)return a..'/'..b end,get_root_dir=function()return '/sdcard' end,
 read_file=function()return '' end,exists=function()return false end,write_file=function()end}
package.preload.storage=function()return storage end
package.loaded.storage=nil;package.loaded.system=nil;package.loaded.board_manager=nil
package.preload.system=function()return {millis=function()return now end,ip=function()return 'test' end,info=function()return {} end}end
package.preload.display=function()return setmetatable({pixel_format='rgb565'},{__index=function()return function()end end})end
package.preload.board_manager=function()return {get_display_lcd_params=function()return 1,2,480,854,1,1 end,get_lcd_touch_handle=function()return 1 end}end
package.preload.lcd_touch=function()return {sync=function()end,poll=function()return sample end}end
package.preload.json=function()return {encode=function(x)return x end}end
local original=dofile
_G.dofile=function(path)
 if path:match('/limits.lua$') then return original(LIMITS_PATH) end
 if path:match('/shell.lua$') then return original(SHELL_PATH) end
 if path:match('/text.lua$') then return {lines=function(s)return {s}end,draw_line=function()end} end
 return original(path)
end
package.preload.device_network=function() return {status=function()return {connected=true,ssid='test',networks={}}end}end
local ui=original(UI_PATH)
ui.navigate('claw')
ui.on_voice_press=function()presses=presses+1;ui.show('recording','voice')end
ui.on_voice_release=function()releases=releases+1 end
ui.show('answer','voice')
sample={just_pressed=true,pressed=true,x=240,y=780};ui.tick();assert(presses==1)
sample={pressed=true,x=240,y=500};ui.tick();assert(releases==0)
sample={pressed=false};ui.tick();assert(releases==0)
now=now+60;sample={pressed=true,x=240,y=780};ui.tick();assert(presses==1 and releases==0)
sample={pressed=false};ui.tick();now=now+130;ui.tick();assert(releases==1)
ui.tick();assert(releases==1)
sample={just_pressed=true,pressed=true,x=240,y=300};ui.tick()
sample={pressed=false};ui.tick();now=now+130;ui.tick();assert(presses==1 and releases==1)
print('PASS: button hit region, hold drag, release outside, duplicate release, answer-area separation')

local runs=0
ui.on_program=function(stopping) assert(not stopping);runs=runs+1 end
ui.set_program('ready')
sample={just_pressed=true,pressed=true,x=100,y=780};ui.tick();assert(runs==1 and presses==1)
sample={pressed=false};ui.tick();now=now+130;ui.tick()
sample={just_pressed=true,pressed=true,x=350,y=780};ui.tick();assert(presses==2 and runs==1)
print('PASS: run button separated from voice button')

for i=1,30 do
 sample={pressed=false};ui.tick();now=now+60
 sample={pressed=true,just_pressed=true,x=350,y=780};ui.tick();now=now+40
end
assert(presses==2 and releases==1)
sample={pressed=false};ui.tick();now=now+130;ui.tick();assert(releases==2)
print('PASS: intermittent missing samples keep a single long hold; stable release submits once')
-- Leaving during a hold must not suppress the first press after returning.
sample={pressed=true,x=350,y=780};ui.tick();local before=presses
ui.navigate('home');sample={pressed=false};ui.tick();now=now+130;ui.tick()
ui.navigate('claw');sample={pressed=true,x=350,y=780};ui.tick()
assert(presses==before+1,'stale held state swallowed first press after returning')
sample={pressed=false};ui.tick();now=now+130;ui.tick()
print('PASS: leaving during hold resets voice button before the next visit')
