from rig import *
import socket
from http.client import HTTPResponse
name='/labplus/qa_upload_guard.bin';old=b'ORIGINAL_QA_20260928';new=b'R'*8192
upload('/labplus/qa_api.lua',(ROOT/'qa_api.lua').read_bytes())
r=Rig();results=[]
def readback():
 with http().open(BASE+'/files'+name,timeout=15) as response:return response.read()
def start_socket():
 s=socket.create_connection(('172.28.58.2',80),timeout=15);s.settimeout(16)
 target='/api/files/upload?path='+urllib.parse.quote(name,safe='')
 s.sendall(('POST '+target+' HTTP/1.1\r\nHost: 172.28.58.2\r\nContent-Type: application/octet-stream\r\nContent-Length: 8192\r\nConnection: close\r\n\r\n').encode()+new[:1024]);return s
try:
 upload(name,old)
 sock=start_socket();time.sleep(.2);sock.close();time.sleep(.5)
 assert readback()==old;results.append({'case':'abort_preserves_existing','passed':True})
 for mode in ['resume_after_6s','idle_timeout']:
  upload(name,old);out={}
  def client():
   sock=start_socket();t=time.monotonic()
   try:
    if mode=='resume_after_6s':time.sleep(6);sock.sendall(new[1024:])
    response=HTTPResponse(sock);response.begin();response.read();out.update(status=response.status,elapsed_s=time.monotonic()-t)
   except Exception as e:out['error']=str(e)
   finally:sock.close()
  t=threading.Thread(target=client);t.start();latencies=[];http_latencies=[]
  while t.is_alive():
   check=time.monotonic();get('memory-status.json');http_latencies.append(time.monotonic()-check)
   latencies.append(r.page('library')['latency_ms']);latencies.append(r.page('home')['latency_ms']);time.sleep(.1)
  t.join();assert 'error' not in out,out
  expected=200 if mode=='resume_after_6s' else 500
  assert out['status']==expected,out
  assert readback()==(new if expected==200 else old)
  assert max(latencies)<3000,latencies
  if mode=='idle_timeout':assert 9<out['elapsed_s']<13,out
  assert max(http_latencies)<2,http_latencies
  out.update(case=mode,ui_max_ms=max(latencies),http_max_s=max(http_latencies),passed=True);results.append(out)
 for i in range(30):
  body=bytes([i])*65536;upload(name,body);assert readback()==body
 results.append({'case':'30_replacements_readback','passed':True})
 r.page('home')
finally:r.save('upload-recovery-console.json');r.close()
(ROOT/'upload-recovery-results.json').write_text(json.dumps(results,indent=2));print('PASS',json.dumps(results),flush=True)
