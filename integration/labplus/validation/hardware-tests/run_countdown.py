import sys,time,json,urllib.request,urllib.parse,uuid
from pathlib import Path
sys.path.insert(0,'/Users/james/esp32-build/runtime/tools');from device import Device
sys.path.insert(0,'/Users/james/esp32-build/device-test-20260927');from product_check import call,get
h=urllib.request.build_opener(urllib.request.ProxyHandler({}));base='http://172.28.58.2'
assert get('product-status.json').get('program')!='running','Preserve the active user program'
name='/labplus/qa_reflash_'+uuid.uuid4().hex[:8]+'.py'
code=b"import sys\nsys.path.append('/sdcard')\nfrom labplus import countdown\ncountdown(10)\nprint('REFLASH_COUNTDOWN_OK')\n"
h.open(urllib.request.Request(base+'/api/files/upload?path='+urllib.parse.quote(name,safe=''),data=code,method='POST',headers={'Content-Type':'application/octet-stream'}),timeout=10).read()
try:
 print(call("print(esp_claw.open_page('program'))"),flush=True)
 d=Device()
 try:
  start=time.monotonic();output=d.command('mpy --run --path /sdcard'+name+' --timeout-ms 15000',20);elapsed=time.monotonic()-start
 finally:d.close()
 assert 'REFLASH_COUNTDOWN_OK' in output and 9.5<elapsed<16,output
 Path(__file__).with_name('countdown-validation.json').write_text(json.dumps({'elapsed_s':elapsed,'console':output},ensure_ascii=False,indent=2))
 print('PASS real 10-second program:',round(elapsed,2),'seconds',flush=True)
finally:
 h.open(urllib.request.Request(base+'/api/files?path='+urllib.parse.quote(name,safe=''),method='DELETE'),timeout=10).read()
 print(call("print(esp_claw.open_page('home'))"),flush=True)
