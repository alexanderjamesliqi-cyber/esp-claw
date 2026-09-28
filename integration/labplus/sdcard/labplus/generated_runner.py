import sys, json
if '/sdcard' not in sys.path:
    sys.path.append('/sdcard')
with open('/sdcard/labplus/program-selection.json') as f:
    selected=json.load(f)
result={'id':selected['id'],'state':'running','output':''}
def save():
    with open('/sdcard/labplus/program-status.json','w') as f:
        json.dump(result,f)
def capture(*items,**kwargs):
    line=kwargs.get('sep',' ').join(str(x) for x in items)+kwargs.get('end','\n')
    if len(result['output'])+len(line)>4000:
        result['overflow']=True
    result['output']=(result['output']+line)[-4000:]
save()
try:
    with open(selected['path']) as f:
        source=f.read()
    exec(source,{'__name__':'__main__','__file__':selected['path'],'print':capture})
    result['state']='done'
except BaseException as e:
    result['state']='failed'
    result['error']=str(e)
finally:
    save()
