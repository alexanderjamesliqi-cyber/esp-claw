-- Bridge for the existing Labplus MicroPython/ESP-Claw firmware.
-- Requests are published by rename and processed sequentially on-device.
local storage = require('storage')
local json = require('json')
local system = require('system')
local capability = require('capability')
local delay = require('delay')
local event_publisher = require('event_publisher')
local ui = dofile('/sdcard/labplus/ui.lua')
local voice = nil
local programs=dofile('/sdcard/labplus/programs.lua')
local resources=dofile('/sdcard/labplus/resources.lua')
local agent = dofile('/sdcard/labplus/agent_bridge.lua')
local root = storage.join_path(storage.get_root_dir(), '.mpy_claw')

if not storage.exists(root) then storage.mkdir(root) end
storage.write_file(root .. '/ready.json', json.encode({version=1}))
print('CLAW_BRIDGE_READY ' .. root)

ui.on_agent_answer=function(answer)
    local prepared=programs.prepare(answer)
    if prepared then
        if prepared.state=='ready' then
            ui.set_program('ready')
            return '程序已生成，点击运行。\n\n'..prepared.code,'ready'
        end
        ui.set_program(nil)
        if prepared.state=='checking' then return '正在检查程序…','checking' end
        print('PROGRAM_VALIDATION_FAILED '..tostring(prepared.error))
        return '程序未通过检查，正在修正…','invalid',prepared.error
    elseif prepared==false then
        ui.set_program(nil)
        if answer:find('activate_skill',1,true) or answer:find('spawn_agent',1,true) then
            return '正在生成适配本机的程序…','invalid','Returned internal commands instead of Python code'
        end
        return nil,'no_code'
    end
end

ui.on_program=function(stopping)
    if not stopping and not resources.admit() then ui.show('当前资源不足，请稍后再运行。','program');return false end
    local ok,err=pcall(function()
        if stopping then programs.stop()
        else
            if voice and voice.status().active then voice.stop();ui.set_voice({active=false}) end
            programs.start();ui.set_program('running');ui.open_program()
            ui.show('程序正在运行…','program')
        end
    end)
    if not ok then
        print('PROGRAM_START_ERROR '..tostring(err))
        ui.show('程序暂时无法运行，请稍后重试。','program')
    end
    return ok
end

local function voice_action(action)
    if action=='press' and programs.running() then ui.show('请先停止当前程序，再开始语音。','voice');return end
    if action=='press' and (not voice or not voice.status().active) and not resources.admit() then ui.show('当前资源不足，请稍后再试。','voice');return end
    local ok,err=pcall(function()
        voice=voice or dofile('/sdcard/labplus/voice.lua')
        if action=='press' and not voice.status().active then
            voice.start(ui);voice.press()
        else
            voice[action]()
        end
        ui.set_voice(voice.status())
    end)
    if not ok then
        if voice then pcall(voice.stop) end
        ui.set_voice({active=false})
        print('VOICE_BUTTON_ERROR '..tostring(err))
        ui.show('暂时无法连接，请稍后重试。','voice')
    end
end
ui.on_voice_press=function() voice_action('press') end
ui.on_voice_release=function() voice_action('release') end


ui.on_leave_claw=function()
    if voice and voice.status().active then voice.stop();ui.set_voice({active=false}) end
end
local startup_pending=true
local startup_at=system.millis()+5500
ui.configure({default_program=programs.default_program,set_default=programs.set_default,
 cancel_startup=function() if startup_pending then print("STARTUP_CANCELLED_BY_TOUCH") end;startup_pending=false end,library=programs.list,preview=programs.read,run_file=function(path)
    local ok,ready,state=pcall(programs.select,path)
    if not ok or not ready then return false,state=='checking' and '解释器正忙，请稍后再试。' or '程序检查未通过，请修改代码。' end
    return ui.on_program(false)
end})

local function process(folder, name)
    local path = folder .. '/request.json'
    if not storage.exists(path) then return end
    local request = json.decode(storage.read_file(path))
    assert(type(request) == 'table' and request.id == name, 'invalid request id')
    assert(type(request.name) == 'string', 'missing capability name')
    if request.name == '__ask' then
        assert(not programs.running(),'program is running')
        assert(type(request.payload) == 'table' and
               type(request.payload.prompt) == 'string', 'missing prompt')
        ui.ask(request.payload.prompt)
        -- Consume before publishing: router file capabilities write the result.
        storage.remove(path)
        event_publisher.publish({
            source_cap='micropython_bridge', event_type='mpy_request',
            event_id='mpy-' .. name, source_channel='micropython',
            target_channel='micropython', chat_id=name, message_id=name,
            content_type='text', text=agent.context(request.payload.prompt),
            session_policy='nosave'
        })
        return
    end
    local ok, output, err
    if request.name == '__diagnostics' then
        local heap=require('system').heap
        ok,output=true,{internal=heap.get_info(heap.caps.INTERNAL),psram=heap.get_info(heap.caps.SPIRAM),lua_kb=collectgarbage('count'),page=ui.product_status()}
    elseif request.name == '__capture' then
        ok,output=require('display').save_frame('/sdcard/labplus/screen.rgb565'),{path='/sdcard/labplus/screen.rgb565',width=480,height=854}
    elseif request.name == '__ui_open' then
        local page=request.payload.page
        assert(page=='home' or page=='claw' or page=='wifi' or page=='library' or page=='program' or page=='settings' or page=='device' or page=='startup','invalid page')
        ui.navigate(page);ok,output=true,ui.product_status()
    elseif request.name == '__product_status' then
        ok,output=true,ui.product_status()
    elseif request.name == '__display_text' then
        assert(type(request.payload.text)=='string' and #request.payload.text<=8000,'invalid display text')
        ui.show(request.payload.text,'program');ok,output=true,{displayed=true}
    elseif request.name == '__voice_start' then
        assert(not programs.running(),'program is running')
        assert(resources.admit(),'resources busy')
        voice = voice or dofile('/sdcard/labplus/voice.lua')
        ok, output = pcall(voice.start, ui, request.payload)
        if not ok then err=tostring(output) end
    elseif request.name == '__voice_press' or request.name == '__voice_release' then
        assert(voice,'voice not started')
        ok, output = pcall(request.name=='__voice_press' and voice.press or voice.release)
    elseif request.name == '__voice_text' then
        assert(voice,'voice not started')
        ok, output = pcall(voice.text, request.payload.prompt)
        if not ok then err=tostring(output) end
    elseif request.name == '__voice_stop' then
        ok, output = true, voice and voice.stop() or {active=false}
    elseif request.name == '__voice_status' then
        ok, output = true, voice and voice.status() or {active=false}
    else
        ok, output, err = capability.call(request.name, request.payload, {
            source_cap='micropython', session_id='micropython-local',
            max_output_bytes=16384
        })
    end
    if storage.exists(folder) and storage.exists(path) then
        storage.remove(path)
        storage.write_file(folder .. '/response.tmp', json.encode({
            id=name, ok=ok, output=output, error=err or output
        }))
        storage.rename(folder .. '/response.tmp', folder .. '/response.json')
    end
end

local studio=dofile('/sdcard/labplus/studio.lua').new(programs,ui,function() return ui.on_program(false) end)

local function service_tick()
    ui.tick()
    if startup_pending and system.millis()>=startup_at then
        startup_pending=false
        local path=programs.default_program()
        print("STARTUP_CHECK",tostring(path),ui.product_status().page)
        if path and not (system.recovery_boot and system.recovery_boot()) and ui.product_status().page=='home' and not ui.product_status().menu then
            local ok,err=pcall(function()
                assert(resources.admit(),'insufficient memory')
                assert(programs.select(path),'program validation failed')
                programs.start(true);ui.set_program('running');ui.open_program()
                ui.show('开机程序正在运行…','program')
            end)
            if not ok then print('STARTUP_PROGRAM_ERROR '..tostring(err));ui.navigate('library') end
        end
    end
    resources.tick()
    studio.tick()
    local entries = storage.listdir(root)
    for _, entry in ipairs(entries) do
        if entry.type == 'dir' and entry.name:match('^[a-f0-9]+_[a-f0-9]+$') then
            local folder = root .. '/' .. entry.name
            local ok, err = pcall(process, folder, entry.name)
            if not ok and storage.exists(folder) then
                pcall(function()
                    storage.remove(folder .. '/request.json')
                    storage.write_file(folder .. '/response.tmp', json.encode({
                        id=entry.name, ok=false, error=tostring(err)
                    }))
                    storage.rename(folder .. '/response.tmp', folder .. '/response.json')
                end)
            end
        end
    end
    local completed=programs.tick()
    if completed then
        ui.set_program(completed.state=='validation_failed' and nil or 'ready')
        if completed.state=='validated' then ui.show('程序已生成，点击运行。\n\n'..completed.code,'program')
        elseif completed.state=='validation_failed' then ui.show('程序检查未通过，请重新生成。','program')
        elseif completed.state=='done' then
            if completed.output~='' then ui.show(completed.output,'program') end
        elseif completed.state=='stopped' then ui.show('程序已停止。','program')
        elseif completed.state=='timeout' then ui.show('程序运行时间已到，已停止。','program')
        else ui.show('程序运行失败，请修改后重试。','program') end
    end
    local speaking = voice and voice.tick()
    if voice then ui.set_voice(voice.status()) end
    return speaking
end
while true do
    local ok,speaking=pcall(service_tick)
    if not ok then
        print('PRODUCT_SERVICE_ERROR '..tostring(speaking))
        collectgarbage('collect')
        if voice then pcall(voice.stop) end
        pcall(programs.stop)
        pcall(ui.show,'当前操作未完成，请返回主页后重试。','voice')
        delay.delay_ms(500)
    else delay.delay_ms(speaking and 1 or 30) end
end
