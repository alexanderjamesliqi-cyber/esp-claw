local fs=require('storage');local json=require('json');local system=require('system');local delay=require('delay');local runner=require('micropython_runner')
local network=require('device_network')
local wifi_entries=0
local folder='/sdcard/.mpy_claw/faded20260928_2'
if not fs.exists(folder) then fs.mkdir(folder) end
local started=system.millis();local count=0;local programs=0;local scans=0;local voices={};local latencies={};local bridge_max=0
local saved=fs.read_file('/sdcard/labplus/program-selection.json')
local function call(name,payload)
 assert(not fs.exists(folder..'/request.json'),'previous request pending')
 if fs.exists(folder..'/response.json') then fs.remove(folder..'/response.json') end
 fs.write_file(folder..'/request.tmp',json.encode({id='faded20260928_2',name=name,payload=payload or {}}));fs.rename(folder..'/request.tmp',folder..'/request.json')
 local t=system.millis()
 while not fs.exists(folder..'/response.json') do assert(system.millis()-t<8000,'UI bridge unresponsive');delay.delay_ms(10) end
 local elapsed=system.millis()-t;bridge_max=math.max(bridge_max,elapsed)
 local response=json.decode(fs.read_file(folder..'/response.json'));fs.remove(folder..'/response.json');assert(response.ok,tostring(response.error))
 return response.output,elapsed
end
local function page(name)
 local _,ms=call('__ui_open',{page=name});assert(ms<3000,'page latency '..ms);latencies[#latencies+1]=ms
end
local function write_json(path,value)
 fs.write_file(path..'.tmp',json.encode(value));if fs.exists(path) then fs.remove(path) end;fs.rename(path..'.tmp',path)
end
local function run_program(name)
 local id='qa_soak_'..programs
 write_json('/sdcard/labplus/program-selection.json',{id=id,path='/sdcard/programs/qa_soak_'..name..'.py',validated=true})
 local ok,message=runner.start(false);assert(ok,message);local job=message:match('Started Python job (%x+)');assert(job,message)
 local t=system.millis();local state
 repeat
  delay.delay_ms(20);local success,list=runner.jobs();assert(success,list);state=list:match(job..' | (%w+) |');assert(system.millis()-t<4000,'program termination timeout')
 until state and state~='queued' and state~='running'
 assert(state=='done',state)
 local result=json.decode(fs.read_file('/sdcard/labplus/program-status.json'))
 assert(result.id==id and result.state==(name=='oom' and 'failed' or 'done'),'program result')
end
local pages={'library','settings','device','startup','home','claw','program','home'}
local names={'ok','fd','dir','oom'}
local ok,err=pcall(function()
 call('__voice_stop');page('home')
 while system.millis()-started<1200000 or count<1000 do
  page(pages[count%#pages+1]);count=count+1
  if count%8==0 then run_program(names[programs%4+1]);programs=programs+1 end
  if count%32==0 then local previous=network.status().generation;page('wifi');wifi_entries=wifi_entries+1;if network.status().generation~=previous then scans=scans+1 end end
  if count%64==0 and #voices<12 then
   page('claw');local before=call('__diagnostics');call('__voice_start')
   local t=system.millis();local s
   repeat s=call('__voice_status');assert(s.active,'voice disconnected before ready');assert(system.millis()-t<20000,'voice ready timeout');delay.delay_ms(100) until s.ready
   call('__voice_press');delay.delay_ms(350)
   if #voices%2==0 then page('home') else call('__voice_release');call('__voice_stop');page('home') end
   s=call('__voice_status');assert(not s.active,'voice still active');local after=call('__diagnostics');voices[#voices+1]={before=before,after=after}
  end
  if count%32==0 then
   local metric=call('__diagnostics');assert(metric.internal.free_size>49152 and metric.internal.largest_free_block>=16384 and metric.psram.free_size>4194304,'resource threshold')
   write_json('/sdcard/labplus/qa_soak_progress.json',{duration_s=(system.millis()-started)/1000,pages=count,program_cycles=programs,voice_cycles=#voices,internal=metric.internal.free_size})
  end
  delay.delay_ms(150)
 end
 page('home')
end)
pcall(function() call('__voice_stop');page('home') end)
fs.write_file('/sdcard/labplus/program-selection.json',saved)
table.sort(latencies)
local summary={passed=ok,error=ok and false or tostring(err),duration_s=(system.millis()-started)/1000,pages=count,program_cycles=programs,wifi_scans=scans,wifi_entries=wifi_entries,voice_cycles=#voices,voice_memory=voices,ui_max_ms=latencies[#latencies],ui_p95_ms=latencies[math.max(1,math.floor(#latencies*.95))],bridge_max_ms=bridge_max,driver='on-device Lua, actual product bridge and user-program runner'}
write_json('/sdcard/labplus/qa_soak_results.json',summary)
print('QA_SOAK_FINISHED '..tostring(ok))
