-- Host simulation tests; these do not validate hardware or the cloud protocol.
local now, incoming, sent, closed, screens = 0, {}, {}, {}, {}
local fail_audio=false
local function object(name)
    return {close=function() closed[name]=(closed[name] or 0)+1 end,
        info=function() return {sample_rate=48000,channels=2,bits=16,bytes_per_frame=4} end,
        read=function(_,n) now=now+40;return string.rep('x',n) end,
        set_mute=function()return true end,
        write=function(_,p) now=now+40;return #p end}
end
package.preload.websocket=function() return {
    new=function(config)
        assert(config.url:match('^wss://'))
        assert(config.configured_auth and not config.headers,'voice must use native credentials')
        return {send=function(_,e) sent[#sent+1]=e end,
                receive=function() return table.remove(incoming,1) end,
                close=function() closed.ws=(closed.ws or 0)+1 end}
    end,
    base64_encode=function(p) return p end,base64_decode=function(p) return p end
} end
package.preload.gpio=function() return {set_level=function(pin,level) assert(pin==12) end} end
package.preload.audio=function() return {
    new_output=function() return object('output') end,
    new_input=function() if fail_audio then error('microphone open failed') end;return object('input') end,
    stream_converter=function(src,dst)
        return {close=function() closed.converter=(closed.converter or 0)+1 end,
          process=function(_,p) return string.rep('x',math.floor(#p*dst.sample_rate*dst.channels/(src.sample_rate*src.channels))) end}
    end
} end
package.preload.board_manager=function() return {
    get_audio_codec_input_params=function() return 1,48000,2,16 end,
    get_audio_codec_output_params=function() return 2,48000,2,16 end
} end
package.preload.json=function() return {
    encode=function(x) if x.type=='session.update' then return '{"type":"session.update","session":{"turn_detection":"manual"}}' end;return x end,
    decode=function(x) if type(x)=='table' then return x end;return {llm_api_key='test-only'} end
} end
package.preload.capability=function() return {call=function(name)
    assert(name~='http_request','voice startup must not wait on the local HTTP server')
    return true,'HTTP 200\nconfig'
end} end
package.preload.system=function() return {millis=function() return now end} end
package.preload.storage=function() return {
    get_root_dir=function() return '/sdcard' end,join_path=function(a,b) return a..'/'..b end,
    write_file=function() end
} end
local ui={show=function(s) screens[#screens+1]=s end,on_agent_answer=function(answer)return answer,'ready' end}
local native_dofile=dofile
local agent_runs=0;local agent_prompts={}
_G.dofile=function(path)
 if path:match('/agent_bridge.lua$') then return {
    start=function(prompt) assert(type(prompt)=='string');agent_prompts[#agent_prompts+1]=prompt;agent_runs=agent_runs+1;return {} end,
    poll=function()return true,{ok=true,answer='from machine import Pin'} end
 } end
 return native_dofile(path)
end
local M=dofile(VOICE_PATH)
assert(M.start(ui).active)
incoming={{type='session.created'}};M.tick()
assert(sent[1]:find('"turn_detection":null',1,true))
assert(not M.status().ready)
incoming={{type='session.updated'}};M.tick()
assert(M.status().ready)
assert(not M.status().speaker_enabled)
now=500;M.tick();assert(M.status().input_bytes==0)
assert(M.press());M.tick();assert(M.status().input_bytes==1280)
assert(not M.release());assert(sent[#sent].type=='input_audio_buffer.clear')
assert(M.press());for i=1,5 do M.tick() end
assert(M.release());assert(sent[#sent-1].type=='input_audio_buffer.commit');assert(sent[#sent].type=='response.create')
local sends=#sent;assert(not M.release());assert(#sent==sends)
local before=M.status().input_bytes
incoming={{type='conversation.item.input_audio_transcription.completed',transcript=''},
          {type='response.created'},{type='response.audio.delta',delta=string.rep('a',1920)},
          {type='response.audio_transcript.delta',delta='你好'},{type='response.done',response={status='completed'}}}
M.tick();assert(M.status().speaker_enabled);assert(M.status().output_bytes==1920);assert(M.status().input_bytes==before)
assert(screens[#screens]:sub(-#'你好')=='你好');assert(M.status().responses==1)
M.tick();assert(not M.status().speaker_enabled);assert(M.status().input_bytes==before) -- echo guard
now=now+500;M.tick();assert(M.status().input_bytes==before)
assert(M.press());M.tick();assert(M.status().input_bytes>before);M.release()
M.stop();M.stop();assert(closed.ws==1 and closed.input==1 and closed.output==1 and closed.converter==2)
M.start(ui);incoming={{type='error',error={message='test connection failure'}}};M.tick()
assert(not M.status().active and M.status().error:find('test connection failure'))
assert(screens[#screens]=='按住下方按钮，开始新对话。')
M.start(ui);now=now+31000;M.tick();assert(not M.status().active)
M.start(ui);incoming={{type='session.updated'}};M.tick()
M.text('device help')
local call={type='response.function_call_arguments.done',name='esp_claw',call_id='call1',arguments={prompt='write board code'}}
incoming={call,call,{type='response.done',response={status='completed'}}};M.tick()
assert(agent_runs==1 and M.status().tool_calls==1)
assert(sent[#sent].item.type=='function_call_output')
local tool_sends=#sent
M.tick();assert(#sent==tool_sends and not M.status().speaking)
assert(screens[#screens]=='from machine import Pin')
incoming={{type='response.audio.delta',delta=string.rep('a',1920)}};M.tick()
assert(M.status().output_bytes==0)

M.stop()
fail_audio=true;M.start(ui);incoming={{type='session.updated'}};M.tick()
assert(not M.status().active and closed.output==3)
assert(not pcall(M.start,ui,{host='untrusted.example.com'}))
print('PASS: handshake, capture, playback, echo guard, transcripts, cleanup, error, timeout, partial-open failure, host validation')

-- Pressing during playback cancels the server and discards late old deltas.
fail_audio=false
M.start(ui);incoming={{type='session.updated'}};M.tick()
M.text('long reply')
incoming={{type='response.created',response={id='old'}},
 {type='response.audio.delta',response_id='old',delta=string.rep('a',9600)}}
M.tick();local played=M.status().output_bytes
assert(M.press());assert(not M.status().speaker_enabled);assert(M.status().holding and M.status().interruptions==1)
assert(sent[#sent-1].type=='response.cancel')
local cancel_id=sent[#sent-1].event_id
incoming={{type='response.audio.delta',response_id='old',delta=string.rep('a',9600)},
 {type='response.done',response={id='old',status='cancelled'}},
 {type='error',error={message='Conversation has none active response'}}}
M.tick();assert(M.status().active and M.status().output_bytes==played)
for i=1,4 do M.tick() end
assert(M.release())
incoming={{type='conversation.item.input_audio_transcription.completed',transcript=''},
 {type='response.created',response={id='new'}},
 {type='response.audio.delta',response_id='old',delta=string.rep('a',9600)},
 {type='response.audio.delta',response_id='new',delta=string.rep('b',1920)},
 {type='response.audio_transcript.delta',response_id='new',delta='新回答'},
 {type='response.done',response={id='new',status='completed'}}}
M.tick();assert(M.status().output_bytes==played+1920);assert(screens[#screens]:sub(-#'新回答')=='新回答')
M.tick()
-- A response completed on the server can still have queued local audio.
M.text('buffered reply')
incoming={{type='response.created',response={id='buffered'}},
 {type='response.audio.delta',response_id='buffered',delta=string.rep('a',9600)},
 {type='response.done',response={id='buffered',status='completed'}}}
M.tick();local n=#sent;assert(M.press());assert(#sent==n+1 and sent[#sent].type=='input_audio_buffer.clear')
M.tick();M.release();M.stop()
-- Cancel before response.created arrives; it must not steal the new turn.
M.start(ui);incoming={{type='session.updated'}};M.tick();M.text('early interrupt');assert(M.press())
incoming={{type='response.created',response={id='early_old'}}};M.tick()
for i=1,4 do M.tick() end
assert(M.release())
incoming={{type='conversation.item.input_audio_transcription.completed',transcript=''},
 {type='response.created',response={id='early_new'}},
 {type='response.audio_transcript.delta',response_id='early_new',delta='新的问题'},
 {type='response.done',response={id='early_old',status='cancelled'}},
 {type='response.done',response={id='early_new',status='completed'}}}
M.tick();assert(screens[#screens]:sub(-#'新的问题')=='新的问题');assert(M.status().active)
M.stop()
print('PASS: barge-in cancels active response, drains queued audio, ignores stale events, records next turn')

M.start(ui);assert(M.press());incoming={{type='session.updated'}};M.tick()
assert(M.status().holding);M.release();M.stop()
M.start(ui);assert(M.press());M.release();incoming={{type='session.updated'}};M.tick()
assert(not M.status().holding);M.stop()
print('PASS: holding through initial connection starts capture; early release disarms it')

M.start(ui);incoming={{type='session.updated'}};M.tick()
assert(M.press());for i=1,5 do M.tick() end;assert(M.release())
incoming={{type='response.created',response={id='program_voice'}},
 {type='response.audio.delta',response_id='program_voice',delta=string.rep('a',1920)}}
M.tick();assert(M.status().output_bytes==0) -- Never play before intent is known.
incoming={{type='conversation.item.input_audio_transcription.completed',transcript='写一个倒计时10秒的程序'},
 {type='response.audio.delta',response_id='program_voice',delta=string.rep('a',1920)},
 {type='response.done',response={id='program_voice',status='cancelled'}}}
M.tick();M.tick()
assert(agent_prompts[#agent_prompts]=='写一个倒计时10秒的程序')
assert(M.status().output_bytes==0 and not M.status().speaking)
M.stop()
local checks=0
ui.on_agent_answer=function(answer) checks=checks+1;if checks<3 then return 'fixing','invalid','not code' end;return answer,'ready' end
M.start(ui);incoming={{type='session.updated'}};M.tick();M.text('write board code')
for i=1,5 do M.tick() end
assert(checks==3 and M.status().output_bytes==0 and not M.status().speaking)
M.stop()
print('PASS: programming transcript routes directly to device agent, stays silent, retries invalid results at most twice')
