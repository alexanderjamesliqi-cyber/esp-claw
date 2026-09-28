from rig import *
import ast
# Wait for normal boot after flashing; this is outside the measured stress interval.
for boot_attempt in range(45):
 try:
  assert get("product-status.json").get("wifi_connected")
  break
 except (OSError,urllib.error.URLError,AssertionError):time.sleep(1)
else:raise RuntimeError("Device did not become ready after boot")
cases=next(ast.literal_eval(n.value) for n in ast.parse((ROOT/'run_faults.py').read_text()).body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='CASES' for t in n.targets))
for n in ['ok','fd','dir','oom']:upload('/programs/qa_soak_'+n+'.py',cases[n])
upload('/labplus/qa_soak.lua',(ROOT/'qa_soak.lua').read_bytes())
for n in ['qa_soak_results.json','qa_soak_progress.json']:
 try:http().open(urllib.request.Request(BASE+'/api/files?path='+urllib.parse.quote('/labplus/'+n,safe=''),method='DELETE'),timeout=10).read()
 except urllib.error.HTTPError as e:
  if e.code!=404:raise
class UploadLoad:
 def __init__(self):self.done=False;self.count=0;self.errors=[]
 def loop(self):
  while not self.done:
   try:upload('/labplus/qa_upload_load.bin',b'x'*65536);self.count+=1
   except Exception as e:self.errors.append({'type':type(e).__name__,'at':time.monotonic()})
   time.sleep(1)
load=UploadLoad();m=Monitor();d=Device();start=time.monotonic();data=bytearray();summary=None
try:
 out=d.command('lua --run-async --path /sdcard/labplus/qa_soak.lua');assert 'Started Lua job' in out,out
 data.extend(out.encode());thread=threading.Thread(target=load.loop,daemon=True);thread.start();m.start();last=0
 while time.monotonic()-start<1400:
  data.extend(d.serial.read(16384))
  if time.monotonic()-last<10:continue
  last=time.monotonic()
  try:
   summary=get('qa_soak_results.json');break
  except urllib.error.HTTPError as e:
   if e.code!=404:raise
  except (urllib.error.URLError,OSError):continue
  try:
   progress=get('qa_soak_progress.json');print('SOAK',json.dumps(progress),flush=True)
  except (urllib.error.URLError,OSError,urllib.error.HTTPError):pass
 else:raise RuntimeError('On-device soak did not terminate')
finally:
 load.done=True
 if 'thread' in locals():thread.join(20)
 d.close();m.stop('soak-monitor.json');(ROOT/'soak-console.log').write_bytes(data)
assert summary, 'no device result'
with http().open(BASE+'/files/labplus/qa_upload_load.bin',timeout=15) as response:
 payload_verified=response.read()==b'x'*65536
summary.update(uploads=load.count,upload_errors=load.errors,errors=m.errors,upload_payload_verified=payload_verified)
(ROOT/'soak-results.json').write_text(json.dumps(summary,indent=2))
assert summary['passed'],summary
assert summary['duration_s']>=1200 and summary['pages']>=1000 and summary['voice_cycles']==12,summary
assert not m.errors and not load.errors,summary
assert payload_verified,'final uploaded content mismatch'
assert not any(marker in data for marker in [b'task_wdt:',b'Guru Meditation',b'Stack canary watchpoint',b'abort() was called',b'ESP-ROM:'])
v=summary['voice_memory'];assert v[-1]['after']['psram']['free_size']>v[1]['after']['psram']['free_size']-512*1024
print('PASS on-device mixed soak',flush=True)
