"""Run the actual board helper against a monotonic clock and slow display."""
from pathlib import Path
import sys,types
root=Path(__file__).resolve().parents[1]
now=[0];frames=[]
def call(name,payload):
 assert name=='__display_text'
 frames.append((now[0],payload['text']))
 now[0]+=130  # Rendering latency must not accumulate into each countdown second.
 return {'displayed':True}
fake_time=types.SimpleNamespace(ticks_ms=lambda:now[0],ticks_diff=lambda a,b:a-b,sleep_ms=lambda ms:now.__setitem__(0,now[0]+ms))
old_time=sys.modules.get('time');old_claw=sys.modules.get('esp_claw')
try:
 sys.modules['time']=fake_time;sys.modules['esp_claw']=types.SimpleNamespace(call=call)
 scope={};exec((root/'sdcard/labplus/__init__.py').read_text(),scope)
 scope['countdown'](10)
 assert [text for _,text in frames]==[str(n) for n in range(10,0,-1)]+['0\n时间到']
 assert 10000<=frames[-1][0]<=10100,frames[-1]
 for value in [-1,60,'10']:
  try:scope['countdown'](value)
  except ValueError:pass
  else:raise AssertionError(value)
finally:
 sys.modules['time']=old_time
 if old_claw is None:sys.modules.pop('esp_claw',None)
 else:sys.modules['esp_claw']=old_claw
print('PASS: 10..0 countdown, monotonic timing despite render latency, invalid arguments')
