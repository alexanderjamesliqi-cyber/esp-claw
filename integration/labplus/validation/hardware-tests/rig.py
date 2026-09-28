import sys,time,json,re,urllib.request,urllib.parse,threading
from pathlib import Path
sys.path.insert(0,'/Users/james/esp32-build/runtime/tools');from device import Device
ROOT=Path(__file__).parent
BASE='http://172.28.58.2'
def http():return urllib.request.build_opener(urllib.request.ProxyHandler({}))
def upload(name,data):
 if isinstance(data,str):data=data.encode()
 return http().open(urllib.request.Request(BASE+'/api/files/upload?path='+urllib.parse.quote(name,safe=''),data=data,method='POST',headers={'Content-Type':'application/octet-stream'}),timeout=15).read()
def get(name):
 for _ in range(5):
  try:return json.load(http().open(BASE+'/files/labplus/'+name,timeout=3))
  except json.JSONDecodeError:time.sleep(.03)
 raise RuntimeError('invalid status JSON')
class Rig:
 def __init__(self):
  self.d=Device();self.events=[];self.latencies=[]
 def command(self,s,timeout=15):
  t=time.monotonic()
  try:out=self.d.command(s,timeout)
  except Exception as e:
   self.events.append({'command':s,'duration':time.monotonic()-t,'error':str(e)});raise
  pending=getattr(self.d,'pending_output','')
  self.events.append({'command':s,'duration':time.monotonic()-t,'output':out,'pending_output':pending})
  if any(x in out+pending for x in ['task_wdt:','Guru Meditation','Stack canary watchpoint','abort() was called']):raise RuntimeError('Native fault in console')
  return out
 def api(self,n,p=None,allow_error=False):
  j=json.dumps({'n':n,'p':p or {}},separators=(',',':'),ensure_ascii=True)
  arg='"'+j.replace('\\','\\\\').replace('"','\\"')+'"'
  out=self.command('lua --run-async --path /sdcard/labplus/qa_api.lua --args-json '+arg,15)
  queued=re.search(r'(?:Queued Lua async job|Started Lua job) ([a-f0-9]+)',out)
  assert queued,out
  until=time.monotonic()+10
  while True:
   out=self.command('lua --job '+queued.group(1))
   match=re.search(r'QA_RESULT (\{[^\n]+\})',out)
   if match or time.monotonic()>until:break
   if 'status=failed' in out or 'status=timeout' in out:break
   time.sleep(.05)
  if not match:raise RuntimeError('No bridge response: '+out[-600:])
  v=json.loads(match.group(1));self.latencies.append(v['latency_ms'])
  if not allow_error:assert v['ok'],v
  return v
 def page(self,page):return self.api('__ui_open',{'page':page})
 def start(self,name,ms=900):
  out=self.command('mpy --run-async --path /sdcard/labplus/qa_'+name+'.py --name qa_job --timeout-ms '+str(ms))
  m=re.search(r'Started Python job ([a-f0-9]+)',out)
  assert m,out
  return m.group(1)
 def wait(self,job,limit=4):
  until=time.monotonic()+limit
  while time.monotonic()<until:
   out=self.command('mpy --jobs');m=re.search(job+r' \| (\w+) \|',out)
   if m and m.group(1) not in ['queued','running']:return m.group(1)
   time.sleep(.08)
  raise RuntimeError('Job failed to terminate: '+job)
 def save(self,name):
  (ROOT/name).write_text(json.dumps({'events':self.events,'ui_latency_ms':self.latencies},ensure_ascii=False,indent=2))
 def close(self):self.d.close()
class Monitor:
 def __init__(self):self.samples=[];self.errors=[];self.transport_events=[];self.done=False;self.offline=False;self.t=threading.Thread(target=self.loop,daemon=True)
 def loop(self):
  last=None;advance=time.monotonic();last_success=time.monotonic()
  while not self.done:
   try:
    value=get('memory-status.json');last_success=time.monotonic();value['host_monotonic']=time.monotonic();self.samples.append(value)
    if len(self.samples)%5==0:
     status=get('product-status.json');value['usb_connected']=status.get('usb_connected');value['wifi_connected']=status.get('wifi_connected')
    now=value['at_ms']
    if last is not None and now<last:self.errors.append('device rebooted')
    if now!=last:advance=time.monotonic()
    elif time.monotonic()-advance>15:self.errors.append('UI heartbeat stalled >15s')
    last=now
   except Exception as e:
    if not self.offline:
     self.transport_events.append({'type':type(e).__name__,'at_s':time.monotonic(),'unavailable_s':time.monotonic()-last_success})
     if time.monotonic()-last_success>15:self.errors.append('HTTP unavailable >15s')
   time.sleep(1)
 def start(self):self.t.start()
 def stop(self,name):
  self.done=True
  if self.t.ident is not None:self.t.join(5)
  (ROOT/name).write_text(json.dumps({'samples':self.samples,'errors':self.errors,'transport_events':self.transport_events},indent=2))
