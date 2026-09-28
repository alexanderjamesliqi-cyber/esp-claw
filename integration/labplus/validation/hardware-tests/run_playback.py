from rig import *
r=Rig();m=Monitor();m.start();results={}
try:
 r.api('__voice_stop');r.page('home');r.page('claw');r.api('__voice_start')
 for _ in range(60):
  s=r.api('__voice_status')['output']
  if s.get('ready'):break
  assert s.get('active'),s
  time.sleep(.3)
 assert s.get('ready'),s
 r.api('__voice_text',{'prompt':'Please tell a long story in Chinese for about one minute.'})
 for _ in range(100):
  s=r.api('__voice_status')['output']
  if s.get('output_bytes',0)>50000 and s.get('speaking'):break
  time.sleep(.3)
 else:raise RuntimeError('No cloud playback')
 results['before']=s
 start=time.monotonic();r.api('__voice_press');s=r.api('__voice_status')['output']
 assert s.get('holding') and s.get('interruptions',0)>=1,s
 results['pressed']=s;results['interrupt_s']=time.monotonic()-start
 time.sleep(.25);r.api('__voice_release');time.sleep(.5)
 for _ in range(60):
  response=r.api('__voice_text',{'prompt':'Reply in Chinese with only: interruption test passed.'},allow_error=True)
  if response['ok']:break
  assert 'voice busy' in str(response),response
  time.sleep(.3)
 else:raise RuntimeError('Voice remained busy after release')
 for _ in range(100):
  s=r.api('__voice_status')['output']
  if s.get('responses',0)>results['before'].get('responses',0) and not s.get('speaking'):break
  assert s.get('active'),s
  time.sleep(.3)
 assert s.get('output_bytes',0)>results['before']['output_bytes'],s
 results['after']=s
 r.api('__voice_stop');r.page('home')
finally:
 r.save('playback-console.json');r.close();m.stop('playback-monitor.json')
assert not m.errors,m.errors
(ROOT/'playback-results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
print('PASS real cloud audio playback, interrupt and subsequent response',flush=True)
