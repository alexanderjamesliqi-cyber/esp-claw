import sys,time,json,urllib.request
from pathlib import Path
sys.path.insert(0,'/Users/james/esp32-build/runtime/tools')
from device import Device
h=urllib.request.build_opener(urllib.request.ProxyHandler({}))
def call(code):
 d=Device()
 try:
  d.enter_python()
  try:
   d.python("import sys;sys.path.append('/sdcard');import esp_claw")
   return d.python(code)
  finally:d.exit_python()
 finally:d.close()
def get(path):return json.load(h.open('http://172.28.58.2/files/labplus/'+path,timeout=5))
if __name__=='__main__':
 print(call('print(esp_claw.product_status())'),flush=True)
 print(get('product-status.json'),flush=True)
