-- Labplus startup screen. Uses the existing board manager LCD driver.
local display = require('display')
local bm = require('board_manager')
local storage = require('storage')
local system = require('system')
local root = storage.join_path(storage.get_root_dir(), 'labplus')
local panel, io, width, height, bus, format = bm.get_display_lcd_params('display_lcd')
assert(panel, 'LCD is unavailable')
-- This custom firmware's working demo uses RGB565 for the actual DSI buffer.
-- Board metadata may report RGB888; do not pass that through.
display.init(panel, io, width, height, bus, 'rgb565')
print('LABPLUS_DISPLAY metadata=' .. tostring(format) .. ' active=' .. tostring(display.pixel_format))
local rgb888 = display.pixel_format == 'rgb888'
local logo = storage.read_file(root .. (rgb888 and '/logo.rgb888' or '/logo.rgb565'))
local started = system.millis()
local last_key = nil
local next_update = 0
local ui = {}
local cjk = dofile(root .. '/text.lua')
local shell_module=dofile(root..'/shell.lua')
local theme=shell_module.palette
local answer_marker = storage.exists(root .. '/claw-answer.id') and storage.read_file(root .. '/claw-answer.id') or ''
local mode, lines, page, pages = nil, {}, 1, 1
local scroll_line, drag_y, drag_start = 0, nil, 0
local title = 'ESP-Claw'
local voice_state='idle'
local program_state=nil
local limits=dofile(root..'/limits.lua')
local ignored_answers={};local ignored_order={}
function ui.ignore_answer(id) if id then ignored_answers[id]=true;ignored_order[#ignored_order+1]=id;if #ignored_order>16 then ignored_answers[table.remove(ignored_order,1)]=nil end end end
local button_held=false
local release_since=nil
local TOUCH_RELEASE_MS=120
local contact_down=false
local draw_claw
local shell
local callbacks={}
function ui.configure(value) callbacks=value end
function ui.navigate(page) shell.go(page) end
local function draw_voice_button()
    local y=height-104
    local label=voice_state=='recording' and '松开发送' or voice_state=='connecting' and '正在连接' or voice_state=='busy' and '正在回答' or '按住说话'
    local x=program_state and 246 or 36
    local w=program_state and width-282 or width-72
    local color=voice_state=='recording' and theme.red or theme.blue
    display.fill_round_rect(x,y,w,72,16,color)
    display.fill_round_rect(x+3,y+3,w-6,66,13,color)
    cjk.draw_line(x+(w-96)//2,y+24,cjk.lines(label,w-12)[1],{color='#FFFFFF',bg=color})
    if program_state and program_state~='running' then
        local running=program_state=='running'
        display.fill_round_rect(36,y,198,72,16,running and theme.red or theme.green)
        display.fill_round_rect(39,y+3,192,66,13,running and theme.red or theme.green)
        cjk.draw_line(111,y+24,cjk.lines(running and '停止' or '运行',180)[1],{color='#FFFFFF',bg=running and theme.red or theme.green})
    end
end
local touch = require('lcd_touch')
local touch_handle = assert(bm.get_lcd_touch_handle('lcd_touch'))
touch.sync(touch_handle)
print('LABPLUS_TOUCH_READY')

local function text(y, value, size, color)
    display.draw_text_aligned(20, y, width - 40, 40, value, {
        font_size=size, color=color, align='center', valign='middle'
    })
end

local function draw(show_status)
    local info = show_status and system.info() or {}
    local ip = system.ip()
    local connected = ip ~= nil and ip ~= '' and ip ~= '0.0.0.0'
    local label = ui.message or (connected and 'Wi-Fi connected' or 'Connecting to Wi-Fi...')
    local ssid = info.wifi_ssid or ''
    -- The display font is ASCII; don't feed it invalid Unicode glyphs.
    local ascii_ssid = ssid:gsub('[\128-\255]', '?')
    display.begin_frame({clear=true, color='white'})
    local logo_y = show_status and 188 or ((height - 146) // 2 - 24)
    display.draw_pixels((width - 294) // 2, logo_y, logo, {
        format=rgb888 and 'rgb888' or 'rgb565', width=147, height=73,
        mode='stretch', dst_width=294, dst_height=146
    })
    text(logo_y + 166, 'labplus.cn', 24, '#777777')
    if show_status then
        display.fill_round_rect(36, 464, width - 72, 174, 16, '#f4f6f8')
        text(483, label, 24, connected and theme.green or '#946500')
        text(531, ascii_ssid ~= '' and ascii_ssid or 'Waiting for network', 20, '#343a40')
        text(574, connected and 'Ready' or 'Reconnecting...', 18, '#707780')
        draw_voice_button()
    end
    display.present()
    display.end_frame()
    storage.write_file(root .. '/screen-status.json', require('json').encode({
        phase=show_status and 'wifi' or 'logo', connected=connected,
        ssid=ssid, ip=ip, width=width, height=height,
        rendered_at_ms=system.millis()
    }))
end

local function save_claw_status()
    storage.write_file(root .. '/screen-status.json',require('json').encode({
        phase='espclaw',route=shell and shell.page or 'boot',state=mode,page=page,pages=pages,line_count=#lines,
        scroll_line=scroll_line,touch_enabled=true,voice_button=voice_state,program=program_state,
        answer_id=answer_marker,rendered_at_ms=system.millis(),ip=system.ip()
    }))
end

draw_claw=function()
    if shell and (shell.page~='claw' or shell.menu) then return end
    display.begin_frame({clear=true,color=theme.bg})
    cjk.draw_line(24,72,cjk.lines('ESP-Claw',width-48)[1],{size=32,bg=theme.bg,color=theme.ink})
    display.fill_round_rect(16,146,width-32,574,20,theme.card)
    cjk.draw_line(24,112,cjk.lines(voice_state=='recording' and '正在聆听' or voice_state=='busy' and '正在回答' or '你的 AI 编程伙伴',width-48)[1],{size=20,bg=theme.bg,color=theme.muted})

    if mode == 'thinking' then
        cjk.draw_line(24,145,cjk.lines('正在处理，请稍候…',width-48)[1])
    end
    local first=scroll_line+1
    local y=mode=='thinking' and 205 or 160
    for i=first,math.min(first+16,#lines) do
        cjk.draw_line(24,y,lines[i]); y=y+30
    end
    draw_voice_button()
    if #lines>17 and mode=='answer' then
        local track=510
        local thumb=math.max(24,math.floor(track*17/#lines))
        local sy=145+math.floor((track-thumb)*scroll_line/math.max(1,#lines-17))
        display.fill_round_rect(width-13,145,5,track,2,'#eef0f3')
        display.fill_round_rect(width-13,sy,5,thumb,2,'#9da8b6')
    end
    if shell then shell.chrome() end
    display.present();display.end_frame()
    save_claw_status()
end
function ui.set_program(value)
    if program_state~=value then program_state=value;if mode then draw_claw() end;if shell and shell.page~='claw' then shell.draw() end end
end
function ui.set_voice(status)
    local value=status.holding and 'recording' or status.active and not status.ready and 'connecting' or status.speaking and 'busy' or 'idle'
    if value~=voice_state then
        voice_state=value
        if shell and (shell.page~='claw' or shell.menu) then return end
        -- Preserve the conversation pixels; only redraw the state and buttons.
        display.begin_frame({clear=false})
        if mode then
            display.fill_rect(24,108,width-48,30,theme.bg)
            cjk.draw_line(24,112,cjk.lines(value=='recording' and '正在聆听' or value=='busy' and '正在回答' or '你的 AI 编程伙伴',width-48)[1],{size=20,bg=theme.bg,color=theme.muted})
        end
        draw_voice_button();display.present();display.end_frame()
        if mode then save_claw_status() end
    end
end
function ui.show(value,kind)
    value=limits.text(value)
    if shell and kind=='program' and (program_state=='running' or shell.page=='program') then shell.program_output(value);return end
    title=kind=='voice' and 'ESP-Claw Voice' or 'ESP-Claw'
    mode='answer';lines=cjk.lines(value,width-48);page=1
    pages=math.max(1,math.ceil(#lines/17));scroll_line=0;drag_y=nil;draw_claw()
end
function ui.ask(prompt)
    title='ESP-Claw'
    answer_marker=storage.exists(root .. '/claw-answer.id') and storage.read_file(root .. '/claw-answer.id') or ''
    mode='thinking';lines=cjk.lines(prompt,width-48)
    -- Keep the pending prompt within the answer area.
    while #lines>14 do table.remove(lines) end
    page=1;pages=1;scroll_line=0;drag_y=nil;draw_claw()
end

shell=shell_module.new({
    program_state=function() return program_state end,
    draw_claw=function() draw_claw() end,
    default_program=function() return callbacks.default_program and callbacks.default_program() end,
    set_default=function(path) return callbacks.set_default(path) end,
    cancel_startup=function() if callbacks.cancel_startup then callbacks.cancel_startup() end end,
    preview=function(path) return callbacks.preview(path) end,
    library=function() return callbacks.library and callbacks.library() or {} end,
    run_file=function(path) return callbacks.run_file(path) end,
    stop_program=function() if ui.on_program then return ui.on_program(true) end return false end,
    leave_claw=function() button_held=false;drag_y=nil;if ui.on_leave_claw then ui.on_leave_claw() end end,
    enter_claw=function() if not mode then ui.show('按住下方按钮说话。\n可以聊天，也可以让 AI 为开发板编程。','voice') end end,
},cjk,logo,width,height)
function ui.open_program() shell.go('program') end
function ui.product_status() return {page=shell.page,menu=shell.menu,fullscreen=shell.page=='program',confirm_stop=shell.confirm_stop or false,animating=shell.animation~=nil} end
draw(false)
print('LABPLUS_LOGO_RENDERED')
function ui.tick()
    local now = system.millis()
    local t=touch.poll(touch_handle)
    -- A single missing sample must not split a held gesture into many presses.
    local was_down=contact_down
    local pressed_edge=t.pressed and not contact_down
    if t.pressed then
        contact_down=true;release_since=nil
    elseif contact_down then
        release_since=release_since or now
        if now-release_since>=TOUCH_RELEASE_MS then contact_down=false;release_since=nil end
    end
    local consumed=shell.handle(t,pressed_edge,was_down and not contact_down)
    if not consumed then
    if pressed_edge and program_state and t.x and t.y and t.x>=36 and t.x<=234 and t.y>=height-104 and t.y<=height-32 then
        if ui.on_program then ui.on_program(program_state=='running') end
        return
    end
    if pressed_edge and not button_held and t.x and t.y and t.x>=(program_state and 246 or 36) and t.x<=width-36 and t.y>=height-104 and t.y<=height-32 then
        button_held=true;drag_y=nil
        print('VOICE_TOUCH_DOWN '..now)
        if ui.on_voice_press then ui.on_voice_press() end
    elseif button_held and not contact_down then
        button_held=false
        print('VOICE_TOUCH_UP '..now)
        if ui.on_voice_release then ui.on_voice_release() end
    end
    if mode=='answer' and not button_held then
        if pressed_edge and t.y and t.y>=120 and t.y<height-115 then
            drag_y=t.y;drag_start=scroll_line
        elseif t.pressed and drag_y and t.y then
            local target=math.max(0,math.min(math.max(0,#lines-17),
                drag_start+(drag_y>=t.y and math.floor((drag_y-t.y)/30) or -math.floor((t.y-drag_y)/30))))
            if target~=scroll_line then
                scroll_line=target;page=math.floor(scroll_line/17)+1;draw_claw()
            end
        end
        if not t.pressed then drag_y=nil end
    end
    end -- active ESP-Claw touch handling
    if shell.page=='boot' and now-started>=1800 then shell.go('home') end
    shell.tick(now)
    if now < next_update then return end
    next_update = now + 1000
    if storage.exists(root .. '/claw-answer.id') then
        local marker=storage.read_file(root .. '/claw-answer.id')
        if ignored_answers[marker] then answer_marker=marker end
        if marker ~= answer_marker then
            local answer=storage.read_file(root .. '/claw-answer.txt')
            answer_marker=marker
            if ui.on_agent_answer then answer=ui.on_agent_answer(answer) or answer end
            mode='answer';lines=cjk.lines(limits.text(answer),width-48)
            page=1;pages=math.max(1,math.ceil(#lines/17));scroll_line=0;drag_y=nil
            draw_claw()
            print('LABPLUS_CLAW_ANSWER_RENDERED pages='..pages)
        end
    end
end
return ui
