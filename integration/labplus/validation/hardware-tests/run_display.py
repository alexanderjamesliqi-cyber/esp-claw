from rig import *
r=Rig();m=Monitor();m.start();results=[]
try:
 for i in range(10):
  value=('word '*1600) if i%2==0 else ''.join(chr(0x4e00+j+i*100) for j in range(2600))
  code="import sys\nsys.path.append('/sdcard')\nfrom labplus import display_text\ndisplay_text("+repr(value)+")\nprint('DISPLAY_OK')\n"
  upload('/labplus/qa_display.py',code)
  r.page('program');start=time.monotonic();state=r.wait(r.start('display',10000),10)
  assert state=='done',state
  shown=time.monotonic()-start;home=r.page('home');assert home['latency_ms']<3000,home
  results.append({'iteration':i,'bytes':len(value.encode()),'render_job_s':shown,'home_ms':home['latency_ms']})
  print('DISPLAY PASS',i,round(shown,2),flush=True)
finally:r.save('display-console.json');r.close();m.stop('display-monitor.json')
assert not m.errors,m.errors
(ROOT/'display-results.json').write_text(json.dumps(results,indent=2))
