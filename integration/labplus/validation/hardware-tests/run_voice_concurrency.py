from rig import *
import socket
from http.client import HTTPResponse
r=Rig();results=[]
try:
 r.api('__voice_stop');r.page('home')
 out={};ready=threading.Event()
 def stalled_upload():
  s=socket.create_connection(('172.28.58.2',80),timeout=15);s.settimeout(16)
  s.sendall(b'POST /api/files/upload?path=%2Flabplus%2Fqa_voice_stall.bin HTTP/1.1\r\nHost: 172.28.58.2\r\nContent-Length: 8192\r\nConnection: close\r\n\r\nx');ready.set()
  try:
   response=HTTPResponse(s);response.begin();response.read();out['status']=response.status
  except Exception as e:out['error']=str(e)
  finally:s.close()
 t=threading.Thread(target=stalled_upload);t.start();assert ready.wait(3)
 lat=[]
 r.page('claw');lat.append(r.api('__voice_start')['latency_ms'])
 lat.append(r.api('__voice_stop')['latency_ms']);lat.append(r.page('home')['latency_ms'])
 while t.is_alive():
  lat.append(r.page('library')['latency_ms']);lat.append(r.page('home')['latency_ms']);time.sleep(.1)
 t.join();assert out.get('status')==500,out;assert max(lat)<3000,lat
 results.append({'case':'voice_start_stop_during_stalled_upload','max_ui_ms':max(lat),'passed':True})
 lat=[];busy=0
 for i in range(20):
  r.page('claw');v=r.api('__voice_start',allow_error=True);lat.append(v['latency_ms'])
  if not v['ok']:busy+=1
  lat.append(r.api('__voice_stop')['latency_ms']);lat.append(r.page('home')['latency_ms']);time.sleep(.15)
 assert max(lat)<3000,lat
 results.append({'case':'20_connect_cancel_cycles','max_ui_ms':max(lat),'bounded_busy':busy,'passed':True})
 time.sleep(12);r.page('claw');r.api('__voice_start')
 for _ in range(80):
  s=r.api('__voice_status')['output']
  if s.get('ready'):break
  assert s.get('active'),s;time.sleep(.25)
 assert s.get('ready'),s
 r.api('__voice_stop');r.page('home')
 results.append({'case':'voice_reconnect_after_cleanup','passed':True})
finally:r.save('voice-concurrency-console.json');r.close()
(ROOT/'voice-concurrency-results.json').write_text(json.dumps(results,indent=2));print('PASS',json.dumps(results),flush=True)
