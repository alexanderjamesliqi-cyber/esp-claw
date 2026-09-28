from rig import *
import os
r=Rig();results=[]
try:
 for i in range(100):
  token='qa_usb_'+str(i)+'_'+('abcdefgh01234567'*23)
  start=time.monotonic();r.d.serial.write((token+'\n').encode());r.d.serial.flush()
  try:out=r.d.read_until(b'app> ',3)
  except TimeoutError as e:
   out=str(e);r.d.serial.write(b'\n');r.d.read_until(b'app> ',4)
  ok=token in out
  results.append({'cycle':i,'ok':ok,'elapsed_s':time.monotonic()-start,'output':out})
  if not ok:print('INPUT LOSS',i,flush=True);break
finally:r.close()
(ROOT/os.environ.get('USB_RESULT','usb-burst-results.json')).write_text(json.dumps(results,indent=2))
assert len(results)==100 and all(x['ok'] for x in results),'USB input loss'
print('PASS 100 bursts of ~380 bytes, no input loss',flush=True)
