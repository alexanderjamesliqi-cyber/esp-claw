local files={['/sdcard/programs/a.py']='print("board")'}
local starts=0;local status='running';local now=1000;local valid=true;local busy=false
package.preload.storage=function()return {
 get_root_dir=function()return '/sdcard'end,join_path=function(a,b)return a..'/'..b end,
 exists=function(p)return files[p]~=nil end,read_file=function(p)return assert(files[p])end,
 write_file=function(p,v)files[p]=v end,rename=function(a,b)files[b]=files[a];files[a]=nil end,mkdir=function(p)files[p]=true end,remove=function(p)files[p]=nil end
}end
package.preload.json=function()return {encode=function(v)return v end,decode=function(v)return v end}end
package.preload.system=function()return {millis=function()now=now+400;return now end}end
package.preload.micropython_runner=function()return {
 validate=function(path)return valid,valid and 'ok' or 'SyntaxError',busy end,
 start=function()starts=starts+1;return true,'Started Python job abc12345 (name=ui_program)'end,
 stop=function()status='stopped';return true,'ok'end,
 jobs=function()return true,'abc12345 | '..status..' | name=ui_program'end
}end
local original=dofile
_G.dofile=function(path) if path:match('/limits.lua$') then
 local limits=original(LIMITS_PATH);limits.read_program=function(p)return assert(files[p])end;return limits
 end;return original(path) end
local M=dofile(PROGRAMS_PATH)
local p=M.prepare('已保存 /sdcard/programs/a.py')
assert(p.code=='print("board")' and starts==0)
files['/sdcard/programs/a.py']='changed'
assert(files[p.path]=='print("board")') -- execution uses the reviewed snapshot
assert(M.prepare('已保存 /sdcard/programs/a.py').path==p.path)
M.start();assert(starts==1);assert(not pcall(M.start))
assert(M.tick()==nil)
M.stop();assert(M.tick().state=='stopped')
assert(M.prepare('This is ordinary conversation')==false)
assert(not pcall(M.start))
assert(M.prepare('```python\nprint(42)\n```').code=='print(42)\n')
assert(starts==1)
print('PASS: code selection without execution, immutable snapshot, explicit start, duplicate start, stop, no-code reply')

valid=false
local bad=M.prepare('```python\ninvalid syntax!\n```')
assert(bad.state=='invalid' and not pcall(M.start))
busy=true;valid=true
local waiting=M.prepare('```python\nprint(99)\n```')
assert(waiting.state=='checking' and not pcall(M.start))
busy=false;assert(M.tick().state=='validated')
M.start();assert(starts==2)
print('PASS: invalid syntax cannot run; a busy VM defers validation without executing code')

M.stop();M.tick()
files['/sdcard/programs/a.py']='print(1)'
M.set_default('/sdcard/programs/a.py');assert(M.default_program()=='/sdcard/programs/a.py')
local fresh=dofile(PROGRAMS_PATH);assert(fresh.default_program()=='/sdcard/programs/a.py')
assert(not pcall(M.set_default,'/sdcard/programs/../escape.py'))
M.set_default(nil);assert(M.default_program()==nil)
valid=false;assert(not pcall(M.set_default,'/sdcard/programs/a.py'));assert(M.default_program()==nil)
print('PASS: default selection survives module restart, cancellation, path and syntax validation')
