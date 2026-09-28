-- Navigation and settings interactions use the actual shell with fake hardware.
local now=0;local written={};local connected={connected=true,ssid='Test',ip='1.2.3.4',networks={{ssid='Test',secured=true},{ssid='Cafe',secured=false}}}
local cancellations=0;local default=nil;local scan_count=0;local credentials=nil;local running=nil;local executions=0;local stops=0;local left=0;local output={}
package.preload.display=function()return setmetatable({},{__index=function()return function()end end})end
package.preload.storage=function()return {write_file=function(p,v)written[p]=v end,read_file=function()return 'print(123)'end}end
package.preload.system=function()return {millis=function()return now end}end
package.preload.json=function()return {encode=function(v)return v end}end
package.preload.device_network=function()return {
 status=function()return connected end,
 scan=function()scan_count=scan_count+1;return true end,
 connect=function(ssid,password)credentials={ssid,password};connected.busy=true;connected.operation='connect';return true end
}end
local S=dofile(SHELL_PATH).new({cancel_startup=function()cancellations=cancellations+1 end,default_program=function()return default end,set_default=function(path)default=path end,program_state=function()return running end,draw_claw=function()end,
 preview=function()return 'print(123)' end,
 library=function()return {{title='Countdown',path='/sdcard/programs/countdown.py'}}end,
 enter_claw=function()end,leave_claw=function()left=left+1 end,
 run_file=function()running='running';executions=executions+1;return true end,
 stop_program=function()running='ready';stops=stops+1 end},
 {lines=function(v)return {v}end,draw_line=function(_,_,v)output[#output+1]=v end},'',480,854)
local function tap(x,y) S.handle({pressed=true,x=x,y=y},true,false);S.handle({pressed=false},false,true) end
local function swipe(y1,y2) S.handle({pressed=true,x=200,y=y1},true,false);S.handle({pressed=true,x=200,y=y2},false,false);S.handle({pressed=false},false,true) end
S.go('home');S.tick(1000)
tap(200,700);assert(cancellations==0) -- stray tap must not suppress startup
swipe(845,720);assert(cancellations==1)
tap(100,560);assert(S.page=='library' and #S.library==1)
tap(100,210);assert(S.page=='detail' and executions==0)
tap(200,650);assert(default=='/sdcard/programs/countdown.py')
tap(200,650);assert(default==nil)
tap(200,650);assert(default=='/sdcard/programs/countdown.py')
tap(340,770);assert(S.page=='program' and executions==1)
swipe(845,730);assert(S.page=='home' and running=='ready' and stops==1)
swipe(20,100);assert(S.menu);tap(100,320);assert(S.page=='device');swipe(845,730);assert(S.page=='home')
tap(100,400);assert(S.page=='claw');swipe(845,720);assert(S.page=='home' and left==1)
swipe(20,100);tap(100,220);assert(S.page=='wifi' and scan_count==1)
S.tick(2000);tap(100,310);assert(S.page=='keyboard' and S.ssid=='Test')
-- q, 1, space, delete, uppercase Q, symbols +
tap(30,530);tap(30,470);tap(280,740);tap(400,740);tap(160,740);tap(30,530)
assert(S.password=='q1Q')
tap(40,740);tap(170,530);assert(S.password=='q1Q+')
assert(not S.visible)
tap(60,340);assert(S.visible);tap(60,340);assert(not S.visible)
tap(380,340);assert(S.page=='wifi' and credentials[1]=='Test' and credentials[2]=='q1Q+' and S.password=='')
connected.busy=false;connected.ok=true;S.tick(3000);assert(S.notice=='连接成功，已保存。')
-- Failure keeps current network status and explains retry without showing raw errors.
tap(350,196);assert(S.page=='keyboard');S.ssid='Bad';S.password='bad-password';tap(380,340)
connected.busy=false;connected.ok=false;S.tick(4000);assert(S.notice:find('连接失败',1,true))
-- Keyboard cancel clears the secret; global home gesture works from input.
tap(350,196);S.password='secret';tap(230,340);assert(S.password=='')
tap(350,196);swipe(845,700);assert(S.page=='home')
print('PASS: product routes, global gestures, preview-before-run, swipe-to-stop, default selection/cancel, settings-only drawer, Wi-Fi scan, password keyboard, success/failure and cancel')
