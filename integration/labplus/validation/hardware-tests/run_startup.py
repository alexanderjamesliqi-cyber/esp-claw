from rig import *
import subprocess
saved={}
assert get('product-status.json').get('program')!='running'
for name in ['startup-program.json','program-selection.json']:
 try:saved[name]=http().open(BASE+'/files/labplus/'+name,timeout=5).read()
 except urllib.error.HTTPError as e:
  if e.code!=404:raise
  saved[name]=None
(ROOT/'startup-before.json').write_text(json.dumps({k:v.decode() if v else None for k,v in saved.items()},indent=2))
try:
 subprocess.run([sys.executable,'-u',str(ROOT/'run_startup_inner.py')],check=True)
finally:
 for name,data in saved.items():
  if data is not None:upload('/labplus/'+name,data)
  else:
   try:http().open(urllib.request.Request(BASE+'/api/files?path='+urllib.parse.quote('/labplus/'+name,safe=''),method='DELETE'),timeout=5).read()
   except urllib.error.HTTPError as e:
    if e.code!=404:raise
 for name in ['/programs/qa_startup.py','/labplus/qa_startup.lua']:
  try:http().open(urllib.request.Request(BASE+'/api/files?path='+urllib.parse.quote(name,safe=''),method='DELETE'),timeout=5).read()
  except urllib.error.HTTPError as e:
   if e.code!=404:raise
 d=Device()
 try:d.serial.write(b'reboot\n')
 finally:d.close()
print('Saved user startup/selection configuration restored',flush=True)
