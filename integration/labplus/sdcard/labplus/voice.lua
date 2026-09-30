-- Runs on the ESP32. No computer relay or stored key in this script.
local wsmod=require('websocket')
local audio=require('audio')
local gpio=require('gpio')
local MAX_PLAYBACK_BYTES=2*1024*1024
local MAX_TRANSCRIPT_BYTES=8192
local bm=require('board_manager')
local json=require('json')
local cap=require('capability')
local system=require('system')
local storage=require('storage')
local root=storage.join_path(storage.get_root_dir(),'labplus')
local agent=dofile(root..'/agent_bridge.lua')
local M={}
local state=nil
local last_error=nil
local function program_request(text)
    local value=(text or ''):lower()
    for _,word in ipairs({'程序','代码','编程','倒计时','countdown','micropython','write code','board code','program using','program to','屏幕显示','显示文字'}) do
        if value:find(word,1,true) then return true end
    end
    return false
end
local function send(s,event) s.ws:send(json.encode(event)) end
local function create_response(s)
    s.awaiting_created=true;s.response_id=nil
    send(s,{type='response.create'})
end
local function show(s,text)
    s.ui.show(text,'voice')
end
local function close_object(obj)
    if obj then pcall(function() obj:close() end) end
end
local function mute_output(s,muted)
    if s.output and s.output_muted~=muted then
        if muted then
            gpio.set_level(12,0)
            assert(s.output:set_mute(true))
        else
            assert(s.output:set_mute(false))
            gpio.set_level(12,1)
        end
        s.output_muted=muted
    end
end
function M.stop()
    local s=state;state=nil
    if not s then return {active=false} end
    if s.agent_job and s.ui.ignore_answer then s.ui.ignore_answer(s.agent_job.id) end
    pcall(mute_output,s,true)
    close_object(s.ws)
    close_object(s.capture_converter);close_object(s.play_converter)
    close_object(s.input);close_object(s.output)
    return {active=false}
end
function M.status()
    local s=state
    return {active=s~=nil,ready=s and s.ready or false,model=s and s.model or nil,
            microphone=s and s.holding or false,
            push_to_talk=true,holding=s and s.holding or false,speaker_enabled=s and s.output~=nil and not s.output_muted or false,
            speaking=s and s.responding or false,
            input_bytes=s and s.input_bytes or 0,output_bytes=s and s.output_bytes or 0,
            interruptions=s and s.interruptions or 0,responses=s and s.responses or 0,tool_calls=s and s.tool_calls or 0,agent_busy=s and s.agent_job~=nil or false,error=last_error}
end
function M.start(ui,config)
    if state then return M.status() end
    config=config or {}
    last_error=nil
    local host=config.host or 'spark.mpython.cn'
    assert(host=='spark.mpython.cn' or host:match('^[a-z0-9%-]+%.cn%-beijing%.maas%.aliyuncs%.com$'), 'invalid realtime host')
    local model=config.model or 'qwen3.5-omni-flash-realtime'
    assert(model:match('^[a-z0-9%.%-]+$'),'invalid model')
    local s={ui=ui,model=model,voice=config.voice or 'Tina',ready=false,
        queue={},head=1,tail=0,offset=1,queued_bytes=0,transcript='',responding=false,
        quiet_until=0,started=system.millis(),last_show=0,
        input_bytes=0,output_bytes=0,responses=0,last_status=0,holding=false,held_bytes=0,tool_calls=0,pending_tools={},seen_calls={},tool_index=1,interruptions=0,ignored_responses={},abandoned_jobs={},drop_created=0}
    s.ws=wsmod.new({url='wss://'..host..'/api-ws/v1/realtime?model='..model,
        configured_auth=true})
    state=s;show(s,'正在连接千问实时语音…')
    return M.status()
end
local function interrupt(s)
    mute_output(s,true)
    s.interruptions=s.interruptions+1
    if s.response_id then s.ignored_responses[s.response_id]=true end
    if s.awaiting_created then s.drop_created=s.drop_created+1 end
    if not s.done and not s.tools_ready and not s.agent_job then
        s.cancel_event='interrupt_'..s.interruptions
        send(s,{type='response.cancel',event_id=s.cancel_event})
    end
    -- Discard local audio immediately; old network deltas are filtered below.
    s.queue={};s.head=1;s.tail=0;s.offset=1;s.queued_bytes=0
    close_object(s.play_converter)
    s.play_converter=audio.stream_converter({sample_rate=24000,channels=1,bits=16},s.output:info())
    if s.agent_job then
        if #s.abandoned_jobs>=4 then table.remove(s.abandoned_jobs,1) end
        s.abandoned_jobs[#s.abandoned_jobs+1]=s.agent_job
        if s.ui.ignore_answer then s.ui.ignore_answer(s.agent_job.id) end
        s.agent_job=nil
    end
    for i=s.tool_index,#s.pending_tools do
        if s.pending_tools[i].call_id then send(s,{type='conversation.item.create',item={type='function_call_output',call_id=s.pending_tools[i].call_id,
            output=json.encode({ok=false,answer='用户已打断本轮回答。已开始的设备操作可能仍在完成，不要声称它已撤销。'})}}) end
    end
    s.pending_tools={};s.tool_index=1;s.tools_ready=false
    s.responding=false;s.done=false;s.awaiting_created=false;s.discard_response=true;s.transcript=''
end
local function route_program(s,prompt)
    if s.program_routed then return end
    if s.responding or s.queue[s.head] or s.agent_job then interrupt(s) end
    s.program_routed=true;s.tool_turn=true;s.expected_program=true
    s.pending_tools={{name='esp_claw',local_call=true,arguments=json.encode({prompt=prompt,task_kind='program'})}}
    s.tool_index=1;s.tools_ready=true;s.responding=true;s.done=false
    show(s,'正在生成适配本机的程序…')
end
function M.press()
    local s=state
    if not s or s.holding then return false end
    if not s.ready then s.press_pending=true;return true end
    s.press_pending=false;s.awaiting_transcript=false
    if s.responding or s.queue[s.head] or s.agent_job then interrupt(s) end
    send(s,{type='input_audio_buffer.clear'})
    s.seen_calls={};s.agent_answer=nil;s.tool_turn=false;s.expected_program=false;s.program_routed=false
    s.holding=true;s.held_bytes=0;s.held_at=system.millis();s.user_text=nil
    -- The button and header show recording without replacing the conversation.
    return true
end
function M.release()
    local s=state
    if not s then return false end
    s.press_pending=false
    if not s.holding then return false end
    s.holding=false
    if s.held_bytes<5120 then
        send(s,{type='input_audio_buffer.clear'})
        show(s,'按住按钮说话，松开发送。')
        return false
    end
    s.awaiting_transcript=true;s.transcription_deadline=system.millis()+15000
    send(s,{type='input_audio_buffer.commit'})
    create_response(s)
    s.responding=true
    show(s,'正在回答…')
    return true
end
function M.text(prompt)
    local s=assert(state,'voice not started')
    assert(s.ready and not s.responding and not s.holding,'voice busy')
    assert(type(prompt)=='string' and #prompt>0 and #prompt<=4000,'invalid prompt')
    s.user_text=prompt;s.seen_calls={};s.agent_answer=nil;s.tool_turn=false;s.expected_program=false;s.program_routed=false
    send(s,{type='conversation.item.create',item={type='message',role='user',content={{type='input_text',text=prompt}}}})
    if program_request(prompt) then route_program(s,prompt)
    else s.responding=true;create_response(s);show(s,'正在处理…') end
    return {accepted=true}
end
local function finish_tools(s)
    if not s.tools_ready then return end
    local call=s.pending_tools[s.tool_index]
    if not call then
        s.pending_tools={};s.tool_index=1;s.tools_ready=false;s.done=false;s.responding=false
        mute_output(s,true)
        return
    end
    local complete,result=false,nil
    if not s.agent_job then
        local ok,value=pcall(function()
            assert(call.name=='esp_claw','unknown tool')
            local args=json.decode(call.arguments)
            call.prompt=args.prompt
            s.expected_program=s.expected_program or args.task_kind=='program' or program_request(args.prompt)
            return agent.start(args.prompt)
        end)
        if ok then
            s.agent_job=value;s.tool_calls=s.tool_calls+1
            show(s,'正在根据开发板接口编写程序…')
        else
            complete=true;result={ok=false,answer='无法处理这项设备请求，请换一种说法。'}
            print('VOICE_AGENT_START_ERROR '..tostring(value))
        end
    end
    if s.agent_job then complete,result=agent.poll(s.agent_job) end
    if complete then
        s.agent_job=nil
        if result.ok then
            local shown,verdict,detail
            if s.ui.on_agent_answer then shown,verdict,detail=s.ui.on_agent_answer(result.answer) end
            local invalid=verdict=='invalid' or (s.expected_program and verdict~='ready' and verdict~='checking')
            if invalid and (call.retries or 0)<2 then
                call.retries=(call.retries or 0)+1
                s.agent_job=agent.start(call.prompt..'\n上次结果无效：'..tostring(detail or '没有完整可运行代码')..
                    '\n请只返回完整的MicroPython python代码块，不要返回技能命令或计划。使用已提供的labplus接口。')
                show(s,'正在检查并修正程序…');return
            elseif invalid then
                result.ok=false;show(s,'暂未生成可运行的程序，请换一种说法重试。')
            else
                s.agent_answer=shown or result.answer
                storage.write_file(root..'/last-agent-answer.md',result.answer)
                show(s,s.agent_answer)
            end
        else show(s,'这项设备请求暂未完成，请重试。') end
        if call.call_id then
            send(s,{type='conversation.item.create',item={type='function_call_output',call_id=call.call_id,
                output=json.encode({ok=result.ok,answer=result.ok and '结果已显示在设备屏幕；代码不朗读，用户点击运行才执行。' or '未完成，已在屏幕说明。'})}})
        end
        s.tool_index=s.tool_index+1
    end
end
local function open_audio(s)
    local c,r,ch,b=bm.get_audio_codec_input_params('audio_adc');assert(c,'microphone unavailable')
    local d,dr,dch,db=bm.get_audio_codec_output_params('audio_dac');assert(d,'speaker unavailable')
    -- Keep paired I2S clocks at the board format. Resample only the network PCM.
    s.output=assert(audio.new_output({d,dr,dch,db,volume=35}))
    mute_output(s,true)
    s.input=assert(audio.new_input({c,r,ch,b,volume=65}))
    local inf=s.input:info();local outf=s.output:info()
    s.capture_converter=audio.stream_converter(inf,{sample_rate=16000,channels=1,bits=16})
    s.play_converter=audio.stream_converter({sample_rate=24000,channels=1,bits=16},outf)
    s.capture_bytes=math.floor(inf.sample_rate*inf.bytes_per_frame*0.04)
    s.ready=true;s.quiet_until=system.millis()+300
    show(s,'实时语音已连接。\n按住下方按钮说话，松开发送。')
    if s.press_pending then M.press() end
end
local function event(s,e)
    local kind=e.type
    if kind=='error' and e.error and s.cancel_event and
       (e.error.event_id==s.cancel_event or e.error.code=='response_cancel_not_active' or
        e.error.message=='Conversation has none active response' or
        e.error.message=='No active response') then
        s.cancel_event=nil;return
    end
    local rid=e.response_id or (e.response and e.response.id)
    if kind=='response.created' then
        if s.drop_created>0 then
            s.drop_created=s.drop_created-1
            if rid then s.ignored_responses[rid]=true end
            return
        end
        if s.holding or not s.awaiting_created then
            if rid then s.ignored_responses[rid]=true end
            return
        end
        s.awaiting_created=false;s.discard_response=false;s.response_id=rid;s.ignored_responses={}
    elseif kind:match('^response%.') and (s.discard_response or (rid and s.ignored_responses[rid]) or (rid and s.response_id and rid~=s.response_id)) then return end
    if kind=='session.created' then
        local update={type='session.update',session={modalities={'text','audio'},voice=s.voice,
            instructions='你是这台Labplus开发板的语音入口。用户要求写代码、修改程序、硬件控制或查询设备能力时，必须调用esp_claw工具，把完整需求和对话中的相关约束交给设备agent，不要自行编造标准Python或硬件API。一般闲聊可以直接回答。工具结果由屏幕展示，不要朗读代码、技能命令、执行计划；等待下一次用户输入。仅工具成功才能说已保存或执行。',
            tools={{type='function',name='esp_claw',description='调用本机ESP-Claw，查询实际MicroPython接口和硬件驱动，生成适配当前开发板的程序。所有编程和设备问题必须使用。',
              parameters={type='object',properties={prompt={type='string',description='用户的完整请求；编程只生成，等待点击运行。'},task_kind={type='string',enum={'program','device'},description='program表示生成程序，device表示设备问答'}},required={'prompt','task_kind'}}}} ,
            enable_input_audio_transcription=true,
            turn_detection='manual',
            audio={input={format={type='pcm',sample_rate=16000}},output={format={type='pcm',sample_rate=24000}}}}}
        -- Lua tables cannot retain nil fields; encode this one field as JSON null.
        s.ws:send((json.encode(update):gsub('"turn_detection":%s*"manual"','"turn_detection":null')))
    elseif kind=='session.updated' and not s.ready then open_audio(s)
    elseif kind=='error' then error(e.error and e.error.message or 'Realtime service error')
    elseif kind=='input_audio_buffer.speech_started' then
        s.transcript='';show(s,'正在听你说话…')
    elseif kind=='conversation.item.input_audio_transcription.completed' then
        s.awaiting_transcript=false
        s.user_text=e.transcript or ''
        if program_request(s.user_text) then route_program(s,s.user_text)
        else show(s,'你：'..s.user_text..'\n\n正在回答…') end
    elseif kind=='response.created' then s.responding=true;s.transcript='';s.done=false
    elseif kind=='response.audio.delta' then
        if s.tool_turn then return end
        local pcm=wsmod.base64_decode(e.delta)
        assert(s.queued_bytes+#pcm<=MAX_PLAYBACK_BYTES,'Audio playback queue overflow')
        s.tail=s.tail+1;s.queue[s.tail]=pcm;s.queued_bytes=s.queued_bytes+#pcm
    elseif kind=='response.audio_transcript.delta' or kind=='response.text.delta' then
        if not s.tool_turn then
            local delta=e.delta or ''
            if #s.transcript+#delta<=MAX_TRANSCRIPT_BYTES then s.transcript=s.transcript..delta end
        end
    elseif kind=='response.function_call_arguments.done' then
        s.tool_turn=true;mute_output(s,true);s.queue={};s.head=1;s.tail=0;s.offset=1;s.queued_bytes=0;s.transcript=''
        if not s.seen_calls[e.call_id] then
            assert(#s.pending_tools<4,'too many tool calls')
            s.seen_calls[e.call_id]=true;s.pending_tools[#s.pending_tools+1]=e
        end
    elseif kind=='response.done' then
        if #s.pending_tools>0 then s.tools_ready=true end
        s.done=true;s.responses=s.responses+1
        if e.response and e.response.status~='completed' then
            show(s,'这次回答未完成，请按住按钮重试。');s.responding=false
        end
        if s.transcript~='' and #s.pending_tools==0 then show(s,s.agent_answer or ((s.user_text and '你：'..s.user_text..'\n\n' or '')..s.transcript)) end
    end
end
local function tick(s)
    local receive_started=system.millis()
    for i=1,64 do
        local message=s.ws:receive(0)
        if not message then break end
        event(s,json.decode(message))
        if system.millis()-receive_started>=12 then break end
    end
    if not s.ready then
        assert(system.millis()-s.started<30000,'Realtime session setup timed out');return
    end
    for i=#s.abandoned_jobs,1,-1 do
        local ok,complete=pcall(agent.poll,s.abandoned_jobs[i])
        if not ok or complete then table.remove(s.abandoned_jobs,i) end
    end
    finish_tools(s)
    if s.awaiting_transcript and system.millis()>=s.transcription_deadline then
        s.awaiting_transcript=false;interrupt(s)
        show(s,'没有识别到说话内容，请按住按钮重试。')
    end
    local chunk=s.queue[s.head]
    if chunk and not s.awaiting_transcript then
        -- 40 ms playback slices let the shared UI service continue polling touch.
        local block=chunk:sub(s.offset,s.offset+1919)
        mute_output(s,false)
        assert(s.output:write(s.play_converter:process(block)))
        s.output_bytes=s.output_bytes+#block;s.queued_bytes=s.queued_bytes-#block
        s.offset=s.offset+#block
        if s.offset>#chunk then s.queue[s.head]=nil;s.head=s.head+1;s.offset=1 end
        s.quiet_until=system.millis()+200
    else
        if system.millis()>=s.quiet_until then mute_output(s,true) end
        if s.done and not s.awaiting_transcript and not chunk and #s.pending_tools==0 then s.responding=false;s.done=false;s.head=1;s.tail=0;mute_output(s,true) end
        local pcm=s.input:read(s.capture_bytes)
        if s.holding and not s.responding then
            local converted=s.capture_converter:process(pcm)
            send(s,{type='input_audio_buffer.append',audio=wsmod.base64_encode(converted)})
            s.input_bytes=s.input_bytes+#converted
            s.held_bytes=s.held_bytes+#converted
            if system.millis()-s.held_at>=60000 then M.release() end
        end
    end
end
function M.tick()
    local s=state;if not s then return false end
    local ok,err=pcall(tick,s)
    if not ok then
        local idle=not s.responding and not s.holding and not s.agent_job
        last_error=tostring(err);M.stop()
        show(s,idle and '按住下方按钮，开始新对话。' or '网络暂时不可用，请按住按钮重试。')
        print('REALTIME_VOICE_STOPPED '..tostring(err))
    end
    local now=system.millis()
    if not state or now-s.last_status>=1000 then
        s.last_status=now
        pcall(storage.write_file,root..'/voice-status.json',json.encode(M.status()))
    end
    return state~=nil
end
return M
