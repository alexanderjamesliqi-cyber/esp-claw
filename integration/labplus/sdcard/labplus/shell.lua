-- Product navigation owns routes and gestures; background services never steal focus.
local display=require('display')
local storage=require('storage')
local system=require('system')
local network=require('device_network')
local json=require('json')
local M={}
local MENU_ANIMATION_MS=360
local MENU_FRAME_MS=40
M.palette={bg="#F3F6FC",card="#FFFFFF",ink="#172B4D",muted="#73829B",blue="#2563EB",green="#159C80",red="#DC4C64",border="#E1E8F2"}
function M.new(host,cjk,logo,w,h)
 local S={page='boot',menu=false,library={},offset=0,wifi={},net={networks={}},notice='',password='',ssid='',focus='password',shift=false,symbols=false,visible=false}
 local theme=M.palette
 local buttons={};local gesture=nil;local next_poll=0;local revision='';local pending=nil;
 local function label(x,y,value,max,style)
  style=style or {};style.bg=style.bg or theme.bg;style.color=style.color or theme.ink
  local size=style.size or 24
  cjk.draw_line(x,y,cjk.lines(tostring(value or ''),(max or w-48)*24//size)[1],style)
 end
 local function box(x,y,bw,bh,title,action,color)
  display.fill_round_rect(x,y,bw,bh,16,color or theme.border)
  local solid=color==theme.blue or color==theme.green or color==theme.red
  display.fill_round_rect(x+2,y+2,bw-4,bh-4,14,solid and color or theme.card)
  local tw=0;for _,cp in utf8.codes(title) do tw=tw+(cp<128 and 12 or 24) end
  label(x+math.max(8,(bw-tw)//2),y+(bh-24)//2,title,bw-12,solid and {color='#FFFFFF',bg=color} or {bg=theme.card})
  buttons[#buttons+1]={x=x,y=y,w=bw,h=bh,action=action}
 end
 local function icon(kind,x,y,color,bg)
  display.fill_round_rect(x,y,48,48,14,bg)
  if kind=='voice' then
   display.fill_round_rect(x+18,y+9,12,23,6,color)
   display.draw_line(x+12,y+25,x+12,y+32,color);display.draw_line(x+36,y+25,x+36,y+32,color)
   display.draw_line(x+12,y+32,x+24,y+38,color);display.draw_line(x+36,y+32,x+24,y+38,color)
   display.fill_rect(x+23,y+36,2,6,color)
  elseif kind=='wifi' then
   for row=0,2 do display.fill_round_rect(x+8+row*5,y+10+row*9,32-row*10,3,1,color) end
   display.fill_circle(x+24,y+37,3,color)
  else
   for row=0,1 do for col=0,1 do display.fill_round_rect(x+9+col*17,y+9+row*17,13,13,3,color) end end
  end
 end
 local function card(y,bh,title,sub,kind,action,primary)
  local bg=primary and theme.blue or theme.card
  display.fill_round_rect(24,y,w-48,bh,22,bg)
  icon(kind,42,y+(bh-48)//2,primary and '#FFFFFF' or theme.blue,primary and '#437BF0' or '#EAF1FF')
  label(108,y+bh//2-26,title,w-146,{size=24,color=primary and '#FFFFFF' or theme.ink,bg=bg})
  label(108,y+bh//2+10,sub,w-146,{size=18,color=primary and '#DCE8FF' or theme.muted,bg=bg})
  buttons[#buttons+1]={x=24,y=y,w=w-48,h=bh,action=action}
 end
 local function notify(message) S.notice=message end
 local function persist_status()
  storage.write_file('/sdcard/labplus/product-status.json',json.encode({page=S.page,menu=S.menu,program=host.program_state(),confirm_stop=S.confirm_stop or false,fullscreen=S.page=='program',animating=S.animation~=nil,usb_connected=S.usb or false,clock=S.clock,default_program=host.default_program and host.default_program(),wifi_connected=S.net.connected or false,wifi_busy=S.net.busy or false,library_count=#S.library,network_count=#S.wifi,rendered_at_ms=system.millis()}))
 end
 function S.chrome()
  display.fill_rect(0,0,w,54,theme.card)
  label(22,16,'LABPLUS',120,{bg=theme.card,color=theme.blue,size=22})
  display.fill_circle(264,26,4,S.net.connected and theme.green or theme.muted)
  label(278,17,S.net.connected and '已连接' or '未连接',100,{size=20,bg=theme.card,color=theme.muted})
  display.draw_line(w-39,22,w-31,30,theme.muted);display.draw_line(w-31,30,w-23,22,theme.muted)
  display.fill_rect(20,53,w-40,1,theme.border)
  display.fill_round_rect((w-112)//2,h-16,112,5,2,'#a9b5c6')
 end
 local function header(title,sub)
  label(24,80,title,w-48,{size=32,color=theme.ink})
  if sub then label(24,127,sub,w-48,{size=20,color=theme.muted}) end
 end
 local function refresh_library()
  local ok,result=pcall(host.library)
  S.library=ok and result or {};if not ok then notify('暂时无法读取程序库。') end
  S.offset=math.min(S.offset,math.max(0,#S.library-6))
 end
 function S.open_menu()
  if S.page=='program' and host.program_state()=='running' then return end
  S.menu=true;S.animation={start=system.millis(),frame=0};gesture=nil
 end
 function S.go(page)
  if host.program_state()=='running' and page~='program' then return end
  if page=='settings' then S.open_menu();return end
  if S.page=='claw' and page~='claw' and host.leave_claw then host.leave_claw() end
  if S.page=='keyboard' and page~='keyboard' then S.password='';S.visible=false end
  if page~='detail' then S.preview=nil end
  S.menu=false;S.animation=nil;S.confirm_stop=false;S.page=page;S.notice='';gesture=nil
  if page=='library' then refresh_library()
  elseif page=='wifi' then
   S.offset=0
   if not S.net.busy then network.scan() end
  elseif page=='claw' then host.enter_claw()
  end
  S.draw()
 end
 local function connect()
  if #S.ssid==0 or #S.ssid>32 then notify('请输入有效的 Wi-Fi 名称。');S.draw();return end
  if #S.password>63 then notify('密码不能超过 63 个字节。');S.draw();return end
  if network.connect(S.ssid,S.password) then
   pending=S.ssid;S.password='';S.visible=false;S.page='wifi';S.offset=0
   notify('正在连接，成功后自动保存…')
  else notify('网络正在处理，请稍后再试。') end
  S.draw()
 end
 local function edit(ssid,secured)
  S.ssid=ssid or '';S.password='';S.visible=false;S.shift=false;S.symbols=false
  S.focus=S.ssid=='' and 'ssid' or 'password';S.secured=secured;S.page='keyboard';S.notice='';S.draw()
 end
 local function key(value)
  local field=S.focus;local content=S[field]
  if value=='DEL' then
   local pos=utf8.offset(content,-1);S[field]=pos and content:sub(1,pos-1) or ''
  elseif value=='SHIFT' then S.shift=not S.shift
  elseif value=='123' then S.symbols=not S.symbols
  elseif value=='SPACE' then if #content<(field=='ssid' and 32 or 63) then S[field]=content..' ' end
  elseif #content+#value<=(field=='ssid' and 32 or 63) then S[field]=content..value end
  S.draw()
 end
 local function keyboard()
  header('连接 Wi-Fi','成功连接后，重启仍会记住此网络')
  box(24,176,w-48,56,S.ssid~='' and S.ssid or '点击输入网络名称',function() S.focus='ssid';S.draw() end,S.focus=='ssid' and '#93B4FF' or nil)
  local password=S.password=='' and '点击输入密码（开放网络可留空）' or S.visible and S.password or string.rep('*',#S.password)
  box(24,248,w-48,56,password,function() S.focus='password';S.draw() end,S.focus=='password' and '#93B4FF' or nil)
  box(24,320,132,46,S.visible and '隐藏密码' or '显示密码',function() S.visible=not S.visible;S.draw() end)
  box(168,320,132,46,'取消',function() S.password='';S.go('wifi') end)
  box(312,320,144,46,'连接',connect,theme.blue)
  label(24,386,S.notice~='' and S.notice or (S.focus=='ssid' and '正在输入：网络名称' or '正在输入：密码'))
  local rows=S.symbols and {'!@#$%^&*()','-_=+[]{}<>',"\\|:;\"',.?/",'`~12345678'} or {'1234567890','qwertyuiop','asdfghjkl','zxcvbnm'}
  for row,value in ipairs(rows) do
   if S.shift then value=value:upper() end
   local count=#value;local bw=42;local x=(w-count*46+4)//2
   for i=1,count do local char=value:sub(i,i);box(x+(i-1)*46,444+(row-1)*65,bw,56,char,function() key(char) end) end
  end
  box(12,710,100,60,S.symbols and 'ABC' or '符号',function() key('123') end)
  box(120,710,100,60,S.shift and '小写' or '大写',function() key('SHIFT') end)
  box(228,710,114,60,'空格',function() key('SPACE') end)
  box(350,710,118,60,'删除',function() key('DEL') end)
 end
 function S.draw()
  if S.page=='boot' then return end
  buttons={}
  if S.page=='claw' and not S.menu then host.draw_claw();persist_status();return end
  display.begin_frame({clear=true,color=theme.bg})
  if S.menu then
   header('设置','网络与设备信息')
   box(24,188,w-48,82,'Wi-Fi 设置',function() S.offset=0;S.go('wifi') end)
   box(24,286,w-48,82,'设备信息',function() S.go('device') end)
   box(24,688,w-48,60,'收起设置',function() S.menu=false;S.draw() end)
  elseif S.page=='device' then
   header('设备信息','LABPLUS · 随身编程伙伴')
   label(24,210,'MicroPython + ESP-Claw')
   label(24,270,'Wi-Fi：'..(S.net.connected and (S.net.ssid or '已连接') or '未连接'))
   label(24,320,'IP：'..(S.net.ip or '未分配'))
   label(24,370,'USB：'..(S.usb and '已连接电脑' or '未连接电脑'))
   label(24,450,'上滑返回主页，下拉打开设置')
  elseif S.page=='home' then
   display.fill_round_rect(24,76,w-48,248,24,theme.card)
   label(42,94,S.date or '连接 Wi-Fi 后自动校时',w-84,{size=20,bg=theme.card,color=theme.muted})
   label(42,134,S.clock or '--:--',w-84,{size=64,bg=theme.card,color=theme.ink})
   label(42,228,'Wi-Fi  '..(S.net.connected and (S.net.ssid or '已连接') or '未连接'),w-84,{size=20,bg=theme.card,color=S.net.connected and theme.green or theme.muted})
   label(42,272,'USB  '..(S.usb and '已连接电脑' or '未连接电脑'),w-84,{size=20,bg=theme.card,color=S.usb and theme.blue or theme.muted})
   card(350,144,'ESP-Claw','按住说话，让想法变成程序','voice',function() S.go('claw') end,true)
   card(514,116,'程序库','运行作品，选择开机程序','library',function() S.offset=0;S.go('library') end)
   local default=host.default_program and host.default_program()
   label(36,678,default and '已设置开机程序' or '尚未设置开机程序',w-72,{size=20,color=theme.muted})
   label(52,758,'下拉设置 · 底部上滑返回主页',w-80,{size=20,color=theme.muted})
  elseif S.page=='wifi' then
   header('Wi-Fi 设置',S.net.connected and ('已连接 '..(S.net.ssid or '')) or '选择网络，连接成功后自动保存')
   box(24,172,198,50,S.net.busy and '处理中…' or '重新扫描',function() if not S.net.busy then network.scan(true);S.draw() end end)
   box(234,172,222,50,'手动添加网络',function() edit('',true) end)
   label(24,240,S.notice~='' and S.notice or S.net.busy and '正在扫描附近网络…' or '点击网络输入密码')
   for i=S.offset+1,math.min(S.offset+6,#S.wifi) do
    local ap=S.wifi[i];local y=282+(i-S.offset-1)*70
    card(y,62,ap.ssid,ap.ssid==S.net.ssid and '当前连接' or (ap.secured and '需要密码' or '开放网络'),'wifi',function() edit(ap.ssid,ap.secured) end)
   end
   if #S.wifi==0 and not S.net.busy then label(24,306,'未找到网络，可重新扫描或手动添加。') end
   box(24,724,132,54,'上一页',function() S.offset=math.max(0,S.offset-6);S.draw() end)
   box(168,724,132,54,'下一页',function() S.offset=math.min(math.max(0,#S.wifi-6),S.offset+6);S.draw() end)
   box(312,724,144,54,'返回',function() S.go('home') end)
  elseif S.page=='keyboard' then keyboard()
  elseif S.page=='library' then
   local default=host.default_program and host.default_program()
   local title='未选择'
   for _,item in ipairs(S.library) do if item.path==default then title=item.title;break end end
   if default and title=='未选择' then title='程序已移除' end
   header('程序库','开机程序：'..title..'（点击设置）')
   buttons[#buttons+1]={x=24,y=120,w=w-48,h=48,action=function() S.go('startup') end}
   for i=S.offset+1,math.min(S.offset+6,#S.library) do
    local item=S.library[i];local y=180+(i-S.offset-1)*84
    card(y,76,item.title,(host.default_program and host.default_program()==item.path) and '开机运行' or item.origin=='ai' and 'AI 生成' or item.origin=='example' and '入门示例' or '我的程序','library',function()
     if host.program_state()=='running' then notify('请先停止当前程序。');S.draw();return end
     local ok,source=pcall(host.preview,item.path)
     if not ok then notify('程序过大或无法读取，最多支持 16 KB。');S.draw();return end
     S.selected=item;S.preview=cjk.lines(source,w-48);S.preview_offset=0;S.page='detail';S.draw()
    end)
   end
   if #S.library==0 then label(24,202,'还没有程序，去 ESP-Claw 创建一个。') end
   label(24,696,S.notice~='' and S.notice or ('共 '..#S.library..' 个程序 · 点击预览后运行'))
   box(24,744,132,54,'上一页',function() S.offset=math.max(0,S.offset-6);S.draw() end)
   box(168,744,132,54,'下一页',function() S.offset=math.min(math.max(0,#S.library-6),S.offset+6);S.draw() end)
   box(312,744,144,54,'刷新',function() refresh_library();S.draw() end)
  elseif S.page=='startup' then
   local default=host.default_program and host.default_program()
   header('开机程序',default and '开机自动运行，上滑确认后退出' or '尚未选择开机程序')
   local title=default and default:match('([^/]+)$') or '无'
   for _,item in ipairs(S.library) do if item.path==default then title=item.title;break end end
   label(24,210,title,w-48)
   box(24,300,w-48,68,'去程序库选择',function() S.go('library') end,theme.blue)
   if default then box(24,388,w-48,68,'取消开机运行',function()
    local ok=pcall(host.set_default,nil);notify(ok and '已取消开机运行。' or '设置未保存，请重试。');S.draw()
   end) end
   label(24,490,S.notice,w-48)
   label(24,560,'选择作品后，在预览页设为开机程序',w-48,{size=20,color=theme.muted})
  elseif S.page=='detail' then
   header(S.selected.title,S.selected.origin=='ai' and 'AI 生成 · 运行前会检查代码' or '本地程序 · 点击运行开始执行')
   display.fill_round_rect(16,164,w-32,444,18,theme.card)
   for i=S.preview_offset+1,math.min(S.preview_offset+14,#S.preview) do cjk.draw_line(24,182+(i-S.preview_offset-1)*30,S.preview[i]) end
   local is_default=host.default_program and host.default_program()==S.selected.path
   box(24,628,w-48,54,is_default and '取消开机运行' or '设为开机程序',function()
    local path=S.selected.path;if is_default then path=nil end
    local ok,err=pcall(host.set_default,path)
    if not ok then notify('设置未保存，请稍后再试。') else notify(is_default and '已取消开机运行。' or '已设置，下次开机自动运行。') end
    S.draw()
   end,is_default and theme.blue or nil)
   label(24,702,S.notice~='' and S.notice or '上下滑动查看代码',w-48,{size=20})
   box(24,746,198,62,'返回程序库',function() S.go('library') end)
   box(234,746,222,62,'运行',function()
    local ok,err=host.run_file(S.selected.path)
    if ok then S.page='program';S.run_text='程序正在运行…';S.draw()
    else notify(err or '程序检查未通过，暂时无法运行。');S.draw() end
   end,theme.green)
  elseif S.page=='program' then
   -- The program owns the entire display; no header, navigation or stop button.
   local ls=cjk.lines(S.run_text or '',w-24)
   local offset=S.run_scroll or 0
   for i=offset+1,math.min(offset+27,#ls) do cjk.draw_line(12,12+(i-offset-1)*30,ls[i],{bg=theme.bg}) end
  end
  if S.page~='program' then S.chrome() end
  if S.confirm_stop then
   buttons={}
   display.fill_round_rect(24,h//2-110,w-48,240,20,theme.card)
   label(48,h//2-76,'结束当前程序？',w-96,{bg=theme.card})
   label(48,h//2-32,S.exiting and '正在结束，请稍候…' or '取消后程序继续运行',w-96,{bg=theme.card,size=20,color=theme.muted})
   if not S.exiting then
    box(48,h//2+36,176,60,'继续运行',function() S.confirm_stop=false;S.draw() end)
    box(240,h//2+36,192,60,'结束运行',function()
     if host.stop_program()~=false then S.exiting=true else S.confirm_stop=false end
     S.draw()
    end,theme.red)
   end
  end
  display.present();display.end_frame();persist_status()
 end
 function S.program_output(value)
  S.run_text=value;S.run_scroll=0;if S.page=='program' and not S.menu then S.draw() end
 end
 function S.handle(t,pressed,released)
  if S.animation or S.exiting then return true end
  if pressed and t.x and t.y then gesture={x=t.x,y=t.y,last_y=t.y,moved=false,page=S.page} end
  if t.pressed and gesture and t.y then
   gesture.last_y=t.y
   if math.abs(t.y-gesture.y)>22 then gesture.moved=true end
   if (gesture.y>=h-28 or S.page=='program') and gesture.y-t.y>60 and not S.confirm_stop then
    gesture=nil;if host.cancel_startup then host.cancel_startup() end
    if host.program_state()=='running' then S.confirm_stop=true;S.draw()
    else S.go('home') end
    return true
   end
   if gesture.y<60 and t.y-gesture.y>55 and S.page~='program' and not S.confirm_stop then
    gesture=nil;S.open_menu();return true
   end
  end
  if released and gesture then
   local g=gesture;gesture=nil
   if not g.moved then
    if g.y<54 and S.page~='program' and not S.confirm_stop then
     if S.menu then S.menu=false;S.draw() else S.open_menu() end;return true
    end
    if S.page~='claw' or S.menu then
     for _,b in ipairs(buttons) do if g.x>=b.x and g.x<=b.x+b.w and g.y>=b.y and g.y<=b.y+b.h then b.action();return true end end
    end
   elseif not S.menu and S.page=='detail' then
    S.preview_offset=math.max(0,math.min(math.max(0,#S.preview-14),S.preview_offset+(g.last_y<g.y and 5 or -5)));S.draw()
   elseif not S.menu and S.page=='program' then
    local count=#cjk.lines(S.run_text or '',w-48)
    S.run_scroll=math.max(0,math.min(math.max(0,count-17),(S.run_scroll or 0)+(g.last_y<g.y and 5 or -5)));S.draw()
   elseif not S.menu and (S.page=='library' or S.page=='wifi') then
    local count=S.page=='library' and #S.library or #S.wifi
    S.offset=math.max(0,math.min(math.max(0,count-6),S.offset+(g.last_y<g.y and 3 or -3)));S.draw()
   end
  end
  return S.page~='claw' or S.menu or (gesture and (gesture.y<60 or gesture.y>=h-28))
 end
 function S.tick(now)
  if S.exiting and host.program_state()~='running' then S.exiting=false;S.go('home')
  elseif S.confirm_stop and host.program_state()~='running' then S.confirm_stop=false;S.draw() end
  if S.animation then
   local elapsed=math.max(0,now-S.animation.start)
   local frame=elapsed//MENU_FRAME_MS+1
   if elapsed>=MENU_ANIMATION_MS then S.animation=nil;S.draw()
   elseif frame>S.animation.frame then
    S.animation.frame=frame
    -- A visible leading edge and eased travel make the downward gesture clear.
    -- Reuse the display buffer; animation never allocates another framebuffer.
    local progress=elapsed/MENU_ANIMATION_MS
    local eased=1-(1-progress)*(1-progress)
    local edge=math.floor(54+(h-54)*eased)
    display.begin_frame({clear=false})
    display.fill_rect(0,0,w,edge,theme.bg)
    display.fill_rect(0,edge-3,w,3,theme.blue)
    display.fill_round_rect((w-80)//2,edge-15,80,5,2,theme.blue)
    display.present();display.end_frame()
   end
   return
  end
  if now<next_poll then return end;next_poll=now+1000
  S.usb=system.usb_connected and system.usb_connected() or false
  local valid=system.time and system.time()>1700000000
  S.clock=valid and system.date('%H:%M') or '--:--'
  S.date=valid and system.date('%Y-%m-%d') or '连接 Wi-Fi 后自动校时'
  local ok,status=pcall(network.status)
  if ok then
   S.net=status;local seen={};S.wifi={}
   for _,ap in ipairs(status.networks or {}) do if ap.ssid~='' and not seen[ap.ssid] then seen[ap.ssid]=true;S.wifi[#S.wifi+1]=ap end end
   if pending and not status.busy then
    notify(status.ok and status.connected and '连接成功，已保存。' or '连接失败，已保留原网络。请检查密码。');pending=nil
   end
   local key=tostring(status.connected)..tostring(status.ssid)..tostring(status.busy)..tostring(status.generation)..S.notice..tostring(S.usb)..S.clock
   if key~=revision then revision=key;if S.page~='keyboard' and S.page~='boot' then S.draw() end end
  end
 end
 return S
end
return M
