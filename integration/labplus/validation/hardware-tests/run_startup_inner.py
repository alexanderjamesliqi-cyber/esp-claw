import sys,time,json,urllib.request,urllib.parse
from pathlib import Path
sys.path.insert(0,'/Users/james/esp32-build/runtime/tools');from device import Device
sys.path.insert(0,'/Users/james/esp32-build/device-test-20260927');from product_check import get
h=urllib.request.build_opener(urllib.request.ProxyHandler({}));base='http://172.28.58.2';evidence={}
def upload(path,data):
 h.open(urllib.request.Request(base+'/api/files/upload?path='+urllib.parse.quote(path,safe=''),data=data.encode(),method='POST',headers={'Content-Type':'application/octet-stream'}),timeout=10).read()
def helper(code):
 upload('/labplus/qa_startup.lua',"local p=dofile('/sdcard/labplus/programs.lua')\n"+code)
 d=Device()
 try:
  result=d.command('lua --run --path /sdcard/labplus/qa_startup.lua',20);print(result,flush=True)
  assert 'lua command failed' not in result
 finally:d.close()
def reboot():
 d=Device();boot=[];started=time.monotonic()
 try:
  d.serial.write(b'reboot\n');d.serial.flush()
  # Keep draining boot output, and let the 5.5 s application startup window elapse.
  while time.monotonic()-started<32:
   raw=d.serial.read(16384).decode(errors='replace')
   boot.extend(line for line in raw.splitlines() if any(k in line for k in ['STARTUP_', 'Guru Meditation', 'task_wdt', 'cap_mpy:', 'rst:']))
 finally:d.close()
 evidence.setdefault('boot_logs',[]).append(boot)
 for _ in range(20):
  try:
   value=get('product-status.json')
   evidence.setdefault('boot_snapshots',[]).append(value)
   Path(__file__).with_name('startup-progress.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2))
   return value
  except Exception:time.sleep(1)
 raise RuntimeError('no UI after reset')
# A real persistent program must not be killed at the manual 60 second limit.
upload('/programs/qa_startup.py',"import time\nfrom labplus import display_text\ndisplay_text('Startup verification')\nwhile True:\n time.sleep_ms(50)\n")
helper("p.set_default('/sdcard/programs/qa_startup.py');assert(p.default_program()=='/sdcard/programs/qa_startup.py');print('DEFAULT_SAVED')")
evidence['boot']=reboot();assert evidence['boot']['page']=='program' and evidence['boot']['program']=='running',evidence['boot']
print('Default program started after reboot; verifying >60s lifetime',flush=True)
time.sleep(55)
evidence['after_70s']=get('product-status.json');assert evidence['after_70s']['program']=='running'
d=Device()
try:
 evidence['stop']=d.command('mpy --stop ui_program',10);print(evidence['stop'],flush=True)
finally:d.close()
time.sleep(2)
helper("p.set_default('/sdcard/programs/hello_labplus.py');assert(p.default_program()=='/sdcard/programs/hello_labplus.py');print('DEFAULT_SWITCHED')")
evidence['switched']=reboot();time.sleep(2)
evidence['selection']=get('program-selection.json');evidence['result']=get('program-status.json')
assert evidence['selection']['path']=='/sdcard/programs/hello_labplus.py' and evidence['result']['state']=='done'
helper("p.set_default(nil);assert(p.default_program()==nil);print('DEFAULT_CANCELLED')")
Path(__file__).with_name('startup-validation.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2))
evidence['cancelled']=reboot();assert evidence['cancelled']['page']=='home' and not evidence['cancelled'].get('default_program')
assert evidence['cancelled']['usb_connected'] is True
assert evidence['cancelled']['clock']!='--:--'
Path(__file__).with_name('startup-validation.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2))
for path in ['/programs/qa_startup.py','/labplus/qa_startup.lua']:
 h.open(urllib.request.Request(base+'/api/files?path='+urllib.parse.quote(path,safe=''),method='DELETE'),timeout=10).read()
print('PASS startup persistence, >60s run, stop, switch, cancel, USB host and synced clock',flush=True)
