"""Real Lua program protocol on a temporary filesystem, with injected rename failure."""
import base64, json, tempfile
from pathlib import Path
from lupa import LuaRuntime, lua_type
source = Path(__file__).resolve().parents[1] / 'sdcard/labplus'
with tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp);(root/'labplus').mkdir();(root/'programs').mkdir()
    lua=LuaRuntime(unpack_returned_tuples=True)
    def plain(v):
        if lua_type(v)!='table': return v
        keys=list(v.keys())
        if keys and all(isinstance(k,int) for k in keys): return [plain(v[i]) for i in range(1,len(keys)+1)]
        return {k:plain(x) for k,x in v.items()}
    def enc(v): return json.dumps(plain(v),ensure_ascii=False)
    def dec(v): return lua.table_from(json.loads(v),recursive=True)
    failures={'target':None}
    def move(a,b):
        if b==failures['target']:
            failures['target']=None
            raise OSError('injected rename failure')
        Path(a).rename(b);return True
    fs=lua.table_from(dict(get_root_dir=lambda:tmp,join_path=lambda a,b:a+'/'+b,
        exists=lambda p:Path(p).exists(),read_file=lambda p:Path(p).read_text(),
        write_file=lambda p,s:bool(Path(p).write_text(s)>=0),remove=lambda p:(Path(p).unlink() or True),
        rename=move,mkdir=lambda p:(Path(p).mkdir() or True),
        listdir=lambda p:lua.table_from([lua.table_from(dict(name=f.name,type='file')) for f in Path(p).iterdir()])))
    lua.globals().FS=fs;lua.globals().JSON=lua.table_from(dict(encode=enc,decode=dec))
    lua.globals().LIMITS=str(source/'limits.lua');lua.globals().STUDIO=str(source/'studio.lua')
    lua.execute('''
package.preload.storage=function()return FS end
package.preload.json=function()return JSON end
package.preload.system=function()return {millis=function()return 1000 end}end
local original=dofile;dofile=function(p)if p:match('/limits.lua$')then return original(LIMITS)end return original(p)end
P={active=nil,default=nil}
function P.list()
 local r={};for _,e in ipairs(FS.listdir(FS.get_root_dir()..'/programs'))do
 if e.name:match('%.py$')then
 local path=FS.get_root_dir()..'/programs/'..e.name
 local m=FS.exists(path..'.json')and JSON.decode(FS.read_file(path..'.json'))or{}
 r[#r+1]={path=path,title=m.title or e.name,id=m.studio_id,origin=m.origin or 'user'}
 end end;table.sort(r,function(a,b)return a.path<b.path end);return r
end
function P.current_path()return P.active end
function P.running()return P.active~=nil end
function P.default_program()return P.default end
function P.forget()end
function P.select(path)P.selected=path;return true end
function P.job_id()return 'ab12' end
function P.status(id)assert(id=='ab12');return {state=P.active and 'running'or 'stopped'}end
function P.stop()P.active=nil end
function NEW()return dofile(STUDIO).new(P,{product_status=function()return {page='home'}end},function()P.active=P.selected;return true end)end
S=NEW()
''')
    def call(op,**args):return plain(lua.globals().S.dispatch(op,lua.table_from(args)))
    def reject(op,**args):
        try:call(op,**args)
        except Exception:return
        raise AssertionError('Unexpected acceptance: '+op)
    def upload(title,code=b'print(42)\n',replace=None):
        kw=dict(title=title,size=len(code),origin='user')
        if replace:kw['replaceId']=replace
        token=call('upload.begin',**kw)['uploadId']
        reject('upload.commit',uploadId=token)
        call('upload.write',uploadId=token,offset=0,data=base64.b64encode(code).decode())
        reject('upload.commit',uploadId=token)
        assert base64.b64decode(call('upload.read',uploadId=token,offset=0,length=len(code))['data'])==code
        return call('upload.commit',uploadId=token)
    assert call('hello')['protocol']==1
    a=upload('中文程序');aid=a['id'];assert call('list')['programs'][0]['title']=='中文程序'
    reject('upload.begin',title='中文程序',size=10)
    call('rename',id=aid,title='重命名');assert call('list')['programs'][0]['id']==aid
    assert call('run',id=aid)['runId']=='ab12'
    reject('rename',id=aid,title='不允许');reject('delete',id=aid)
    reject('upload.begin',title='重命名',size=10,replaceId=aid)
    call('stop');upload('重命名',b'print(99)\n',aid)
    path=next((root/'programs').glob('*.py'));assert path.read_text()=='print(99)\n'
    failures['target']=str(path)+'.json'
    reject('rename',id=aid,title='失败不改变');assert call('list')['programs'][0]['title']=='重命名'
    # Power loss after moving one half of a pair must roll it back on restart.
    backup=str(path)+'.studio-old';path.rename(backup)
    path.write_text('corrupt replacement')
    (root/'labplus/studio-transaction.json').write_text(json.dumps([dict(path=str(path),source=str(path)+'.new',backup=backup,existed=True)]))
    (root/'labplus/studio-request.json').write_text('{"op":"run"}')
    lua.execute('S=NEW()');assert path.read_text()=='print(99)\n'
    assert not (root/'labplus/studio-request.json').exists()
    call('delete',id=aid);assert not path.exists() and not Path(str(path)+'.json').exists()
    reject('delete',id='../system');assert call('list')['programs']=={}
    for n in range(10):upload('程序'+str(n))
    page=call('list',limit=8.0);assert len(page['programs'])==8
    assert len(call('list',cursor=page['nextCursor'],limit=8)['programs'])==2
    call('rename',id=page['programs'][0]['id'],title='列表变化')
    reject('list',cursor=page['nextCursor'],limit=8)
    request=root/'labplus/studio-request.json'
    request.write_text(json.dumps(dict(v=1,id='lost-reply',op='rename',args=dict(id=page['programs'][0]['id'],title='响应丢失仍只执行一次'))))
    failures['target']=str(root/'labplus/studio-response.json')
    lua.execute('S.tick();S.tick()')
    assert not request.exists() and not (root/'labplus/studio-response.json').exists()
    assert any(p['title']=='响应丢失仍只执行一次' for p in call('list')['programs'])
    lua.execute("function P.status()return {state='done',output=string.rep(string.char(0),4000),error=string.rep('错',4000)}end")
    bounded=call('status',runId='abc');assert bounded['overflow'] and len(json.dumps(bounded,ensure_ascii=False).encode())<16000
    print('PASS: studio upload/readback/commit, Chinese CRUD, running guards, rollback, reboot recovery, pagination')
