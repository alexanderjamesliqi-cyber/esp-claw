from rig import *
results=[]
for code in ['x=(1<<1000000)-1; y=x*x',"('a'*350000).find('a'*170000+'b')","raise ValueError((1<<500000)-1)","exec('while True: pass')",'import time;time.sleep_us(30000000)',"exec('try:\\n while True: pass\\nfinally:\\n while True: pass')"]:
 d=Device()
 try:
  d.enter_python();time.sleep(.1);before=get('memory-status.json')['at_ms']
  d.serial.write((code+'\r').encode());time.sleep(6)
  after=get('memory-status.json')['at_ms'];assert after>before,'UI stalled during REPL execution'
  start=time.monotonic();d.serial.write(b'\x03');output=d.read_until(b'app> ',4);elapsed=time.monotonic()-start
  assert 'task_wdt' not in output and 'Guru Meditation' not in output,output
  results.append({'code':code,'interrupt_s':elapsed,'ui_before':before,'ui_after':after,'output':output})
  print('REPL INTERRUPT PASS',round(elapsed,3),flush=True)
 finally:d.close()
d=Device()
try:
 d.enter_python();time.sleep(.1)
 d.serial.write(b"exec('def f(): return f()\\nf()')\r")
 output=d.read_until(b'>>> ',4);assert 'RuntimeError' in output and 'Guru' not in output,output
 results.append({'recursive_repl':output})
 assert '55' in d.python('print(sum(range(11)))')
 d.exit_python()
finally:d.close()
(ROOT/'repl-results.json').write_text(json.dumps(results,indent=2))
print('PASS REPL interrupt, swallowed finally and recursion recovery',flush=True)
