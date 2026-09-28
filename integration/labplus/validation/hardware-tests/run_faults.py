from rig import *
CASES={
'gc_finalizer':'import gc\nclass A:\n def __del__(self):\n  while True: pass\na=A()\na=None\ngc.collect()\n',
'scheduled_callback':'import micropython,time\ndef f(x):\n while True: pass\nmicropython.schedule(f,None)\ntime.sleep_ms(60000)\n',
'machine_timer':"from machine import Timer\nTimer(0)\n",
'machine_rtc':"from machine import RTC\nRTC()\n",
'pin_irq':"from machine import Pin\nPin(35).irq(handler=lambda p:None)\n",
'builtin_sum':'sum(range(1000000000))\n',
'builtin_all':'all(range(1,1000000000))\n',
'builtin_max':'max(range(1000000000))\n',
'builtin_min':'min(range(1000000000))\n',
'bigint_error':"raise ValueError((1<<500000)-1)\n",
'bigint_mul':'x=(1<<1000000)-1\ny=x*x\n',
'bigint_div':'x=(1<<1000000)-1\ny=(1<<500001)+123\nz=x//y\n',
'bigint_str':'str((1<<500000)-1)\n',
'bigint_parse':"int('9'*100000)\n",
'str_find':"('a'*350000).find('a'*170000+'b')\n",
'str_count':"('a'*350000).count('a'*170000+'b')\n",
'str_split':"('a'*350000).split('a'*170000+'b')\n",
'str_rsplit':"('a'*350000).rsplit('a'*170000+'b')\n",
'loop':'while True: pass\n',
'catch':'while True:\n try:\n  while True: pass\n except BaseException: pass\n',
'finally':'try:\n while True: pass\nfinally:\n while True: pass\n',
'sleep_ms':'import time\ntime.sleep_ms(60000)\n',
'sleep_us':'import time\ntime.sleep_us(30000000)\n',
'input':"import sys\nsys.stdin.read(1)\n",
'oom':'x=bytearray(2*1024*1024)\n',
'recursion':'def f(): return f()\nf()\n',
'json_depth':"import json\njson.dumps(json.loads('['*5000+'0'+']'*5000))\n",
'file_readall':"f=open('/sdcard/labplus/font24.bin','rb');f.read()\n",
'file_oom':"f=open('/sdcard/labplus/font24.bin','rb');f.read(2*1024*1024)\n",
'exception':"raise ValueError('injected error')\n",
'native':'import micropython\n@micropython.native\ndef f(): return 1\nf()\n',
'viper':'import micropython\n@micropython.viper\ndef f(): return 1\nf()\n',
'fd':"f=open('/sdcard/labplus/board_context.md');print('FD_OK')\n",
'dir':"import os\nf=os.ilistdir('/sdcard/labplus');print('DIR_OK')\n",
'fd_quota':"a=[]\nfor i in range(20): a.append(open('/sdcard/labplus/board_context.md'))\n",
'fd_abort':"f=open('/sdcard/labplus/board_context.md')\nwhile True: pass\n",
'print':"while True: print('x'*2048)\n",
'ok':"print('QA_OK',sum(range(100)))\n",
'wifi':"import labplus_wifi\nlabplus_wifi.connect('LABPLUS_STABILITY_NO_SUCH_AP','invalid-test-password',timeout_ms=30000)\n",
}
for n,c in CASES.items():upload('/labplus/qa_'+n+'.py',c)
upload('/labplus/qa_api.lua',(ROOT/'qa_api.lua').read_bytes())
r=Rig();m=Monitor();m.start();results=[]
try:
 r.page('home')
 for name in ['gc_finalizer', 'scheduled_callback']+['builtin_sum', 'builtin_all', 'builtin_max', 'builtin_min']+['bigint_error','bigint_mul', 'bigint_div', 'bigint_str', 'bigint_parse', 'str_find', 'str_count', 'str_split', 'str_rsplit']+['machine_timer','machine_rtc','pin_irq','loop','catch','finally','sleep_ms','sleep_us','input','oom','recursion','json_depth','file_readall','file_oom','exception','native','viper','fd_quota','fd_abort','print']:
  started=time.monotonic();job=r.start(name,1000)
  ui=r.page('library');state=r.wait(job,4);elapsed=time.monotonic()-started
  if name=='gc_finalizer':assert state in ['done','timeout'],(name,state)
  else:assert state==('timeout' if name in ['gc_finalizer', 'scheduled_callback']+['loop','catch','finally','sleep_ms','sleep_us','fd_abort','print','file_readall']+['builtin_sum', 'builtin_all', 'builtin_max', 'builtin_min']+['bigint_error','bigint_mul', 'bigint_div', 'bigint_str', 'bigint_parse', 'str_find', 'str_count', 'str_split', 'str_rsplit'] else 'failed'),(name,state)
  assert elapsed<5,(name,elapsed)
  r.page('home');results.append({'case':name,'state':state,'elapsed_s':elapsed,'ui_ms':ui['latency_ms']})
  print('FAULT PASS',name,state,round(elapsed,3),'UI',ui['latency_ms'],flush=True)
 # Explicit stop including a finally block which attempts to swallow shutdown.
 for name in ['loop','finally','sleep_us','fd_abort','file_readall','bigint_mul','str_find','builtin_sum']:
  job=r.start(name,30000);r.page('settings');start=time.monotonic();r.command('mpy --stop qa_job');state=r.wait(job,3)
  assert state=='stopped' and time.monotonic()-start<3,(name,state)
  results.append({'case':name+'_stop','state':state,'stop_s':time.monotonic()-start})
 # Repeated VM shutdown must release both ordinary files and directory iterators.
 for i in range(100):
  name=['fd','dir','ok'][i%3];job=r.start(name,1000);assert r.wait(job)=='done'
  if i%10==0:r.page('library');r.page('home');print('RESOURCE CYCLES',i+1,flush=True)
 # The VM stays exclusive while a long job is running, and recovers immediately.
 job=r.start('loop',30000)
 second=r.command('mpy --run-async --path /sdcard/labplus/qa_ok.py --name qa_second --timeout-ms 1000')
 assert 'concurrency limit' in second or 'busy' in second,second
 r.command('mpy --stop qa_job');assert r.wait(job)=='stopped';assert r.wait(r.start('ok',1000))=='done'
 # Deliberate disconnection: watch UI via the serial bridge while HTTP is unavailable.
 m.offline=True;start=time.monotonic();job=r.start('wifi',1500);r.page('settings');state=r.wait(job,8)
 assert state=='timeout',(state,time.monotonic()-start)
 r.page('home')
 for _ in range(45):
  try:
   if get('product-status.json')['wifi_connected']:break
  except Exception:pass
  time.sleep(.5)
 else:raise RuntimeError('Saved Wi-Fi did not recover')
 m.offline=False;results.append({'case':'wifi_cancel_restore','state':state,'restored_s':time.monotonic()-start})
 print('WIFI RESTORED',round(time.monotonic()-start,3),flush=True)
 (ROOT/'fault-results.json').write_text(json.dumps(results,indent=2))
finally:
 r.save('fault-console.json');r.close();m.stop('fault-monitor.json')
print('MONITOR ERRORS',m.errors,flush=True)
assert not m.errors,m.errors
print('PASS fault suite + 100 resource lifecycle runs',flush=True)
