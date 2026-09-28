from rig import *
source='''local ws=require('websocket');local delay=require('delay')
local created,busy=0,0
for i=1,20 do
 local ok,w=pcall(ws.new,{url='wss://192.0.2.1:443/'})
 if ok then
  created=created+1
  if i%2==0 then w:close();w:close() end
 else busy=busy+1 end
 w=nil;collectgarbage('collect');delay.delay_ms(150)
end
assert(created>=2 and busy>0,'bounded client admission not exercised')
print('GC_RESULT created='..created..' busy='..busy)
'''
upload('/labplus/qa_ws_gc.lua',source)
r=Rig();lat=[];result={}
try:
 out=r.command('lua --run-async --path /sdcard/labplus/qa_ws_gc.lua');job=re.search(r'Started Lua job ([a-f0-9]+)',out).group(1)
 deadline=time.monotonic()+30
 while time.monotonic()<deadline:
  lat.append(r.page('library')['latency_ms']);lat.append(r.page('home')['latency_ms'])
  out=r.command('lua --job '+job)
  if 'GC_RESULT' in out:break
  assert 'status=failed' not in out,out
 else:raise RuntimeError('GC test timeout')
 assert max(lat)<3000,lat
 # A maximum of two sequential 10s network cleanups may still be pending.
 end=time.monotonic()+25
 while time.monotonic()<end:
  lat.append(r.page('home')['latency_ms']);time.sleep(.5)
 r.page('claw');r.api('__voice_start')
 for _ in range(80):
  s=r.api('__voice_status')['output']
  if s.get('ready'):break
  assert s.get('active'),s;time.sleep(.25)
 assert s.get('ready'),s
 r.api('__voice_stop');r.page('home')
 result={'passed':True,'max_ui_ms':max(lat),'gc_summary':re.search(r'GC_RESULT[^\n]+',out).group(0),'reconnect':True}
finally:r.save('websocket-gc-console.json');r.close()
(ROOT/'websocket-gc-results.json').write_text(json.dumps(result,indent=2));print('PASS',json.dumps(result),flush=True)
