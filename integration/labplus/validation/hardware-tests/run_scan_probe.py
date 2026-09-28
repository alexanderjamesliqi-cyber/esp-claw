from rig import *
upload('/labplus/qa_scan_probe.lua', '''local n=require('device_network');local s=require('system');local d=require('delay');local j=require('json');local fs=require('storage');local rows={}
for i=1,10 do
 local t=s.millis();assert(n.scan(true));repeat d.delay_ms(30) until not n.status().busy
 local result=n.status();assert(result.ok);assert(n.scan());assert(n.status().generation==result.generation and not n.status().busy);assert(n.scan(true));assert(n.status().generation==result.generation and not n.status().busy);rows[#rows+1]={elapsed_ms=s.millis()-t,count=#result.networks};print('SCAN '..rows[#rows].elapsed_ms);d.delay_ms(5100)
end
fs.write_file('/sdcard/labplus/qa_scan_results.json',j.encode(rows));print('SCAN_PROBE_DONE')''')
class Load:
 def __init__(self):self.done=False;self.errors=[];self.latencies=[]
 def loop(self):
  while not self.done:
   t=time.monotonic()
   try:upload('/labplus/qa_upload_load.bin',b'x'*65536);self.latencies.append(time.monotonic()-t)
   except Exception as e:self.errors.append(type(e).__name__)
   time.sleep(.5)
l=Load();thread=threading.Thread(target=l.loop,daemon=True);thread.start();m=Monitor();m.start();r=Rig();records={}
try:
 out=r.command('lua --run-async --path /sdcard/labplus/qa_scan_probe.lua');job=re.search(r'Started Lua job ([a-f0-9]+)',out).group(1)
 start=time.monotonic()
 while time.monotonic()-start<180:
  r.page('library');r.page('home');out=r.command('lua --job '+job)
  if 'status=done' in out:break
  assert 'status=failed' not in out,out
  time.sleep(.5)
 else:raise RuntimeError('Scan probe did not complete')
finally:
 r.close();r.save('scan-console.json');l.done=True;thread.join(20);m.stop('scan-monitor.json')
rows=get('qa_scan_results.json');records={'scans':rows,'upload_s':l.latencies,'upload_errors':l.errors,'monitor_errors':m.errors,'cached_reopen_and_refresh_cooldown':True};(ROOT/'scan-results.json').write_text(json.dumps(records,indent=2))
assert len(rows)==10 and max(x['elapsed_ms'] for x in rows)<6000 and min(x['elapsed_ms'] for x in rows)>1000,rows
assert not l.errors and not m.errors,records
print('PASS',json.dumps(records),flush=True)
