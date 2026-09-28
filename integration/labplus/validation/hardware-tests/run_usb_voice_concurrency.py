from rig import *
upload('/labplus/qa_api.lua',(ROOT/'qa_api.lua').read_bytes())
r=Rig();m=Monitor();m.start();load={'done':False,'uploads':0,'errors':[]};s={}
def uploader():
 while not load['done']:
  try:upload('/labplus/qa_upload_load.bin',b'x'*65536);load['uploads']+=1
  except Exception as e:load['errors'].append(type(e).__name__)
  time.sleep(.5)
try:
 r.api('__voice_stop');r.page('claw');r.api('__voice_start')
 for _ in range(80):
  s=r.api('__voice_status')['output']
  if s.get('ready'):break
  assert s.get('active'),s;time.sleep(.2)
 assert s.get('ready'),s
 r.api('__voice_text',{'prompt':'请用中文讲一个大约一分钟的简短故事。'})
 thread=threading.Thread(target=uploader);thread.start();max_audio=0
 for i in range(100):
  if i and i%5==0:r.d.close();r.d=Device()
  s=r.api('__voice_status',{'sequence':i,'padding':'p'*160})['output'];assert s.get('active'),s;max_audio=max(max_audio,s.get('output_bytes',0))
 assert max_audio>50000,max_audio
 r.api('__voice_press');r.api('__voice_release');r.api('__voice_stop');r.page('home')
finally:
 load['done']=True
 if 'thread' in locals():thread.join(20)
 r.save('usb-voice-concurrency-console.json');r.close();m.stop('usb-voice-concurrency-monitor.json')
result={'commands':100,'serial_reopens':19,'cloud_output_bytes':max_audio,'uploads':load['uploads'],'upload_errors':load['errors'],'monitor_errors':m.errors,'max_ui_ms':max(r.latencies)}
(ROOT/'usb-voice-concurrency-results.json').write_text(json.dumps(result,indent=2));assert not load['errors'] and not m.errors,result;print('PASS',json.dumps(result),flush=True)
