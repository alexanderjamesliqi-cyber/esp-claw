local storage=require('storage')
local json=require('json')
local system=require('system')
local runner=require('micropython_runner')
local limits=dofile('/sdcard/labplus/limits.lua')
local root=storage.join_path(storage.get_root_dir(),'labplus')
local dir=storage.join_path(storage.get_root_dir(),'programs')
local cached=nil
local M={};local selected=nil;local job=nil;local last_answer=nil;local sequence=0;local last_poll=0;local last_result=nil;local last_job=nil
local function validate_selected()
    local forbidden={tkinter=true,pygame=true,requests=true,numpy=true,network=true,framebuf=true}
    for line in cached.code:gmatch('[^\n]+') do
        local imported=line:match('^%s*import%s+([%w_]+)') or line:match('^%s*from%s+([%w_]+)')
        if imported and forbidden[imported] then
            cached.state='invalid';cached.error='Unsupported module on this board: '..imported;selected.validated=false;storage.write_file(root..'/program-validation.json',json.encode({id=selected.id,ok=false,error=cached.error}));return
        end
    end
    local ok,message,busy=runner.validate(selected.path)
    if busy then cached.state='checking';return end
    cached.state=ok and 'ready' or 'invalid';cached.error=not ok and message or nil
    selected.validated=ok
    storage.write_file(root..'/program-selection.json',json.encode(selected))
    storage.write_file(root..'/program-validation.json',json.encode({id=selected.id,ok=ok,error=cached.error}))
end
function M.prepare(answer)
    if job then return nil end
    if answer==last_answer then return cached end
    last_answer=answer
    local path=answer:match('(/sdcard/programs/[%w_/%-]+%.py)')
    local code=nil
    if path and not path:find('..',1,true) and storage.exists(path) then code=limits.read_program(path) end
    if not code then code=answer:match('```[Pp]ython%s*\n(.-)```') or answer:match('```[Mm]icro[Pp]ython%s*\n(.-)```') end
    if not code or #code==0 or #code>limits.PROGRAM_BYTES then selected=nil;cached=false;return false end
    if not storage.exists(dir) then storage.mkdir(dir) end
    sequence=sequence+1
    local id=string.format('%x_%x',system.millis(),sequence)
    local snapshot=dir..'/generated_'..id..'.py'
    assert(not storage.exists(snapshot),'program path collision')
    storage.write_file(snapshot,code)
    local title=code:match('countdown%((%d+)%)')
    title=title and title..' 秒倒计时' or 'AI 程序 '..id
    storage.write_file(snapshot..'.json',json.encode({title=title,origin='ai'}))
    selected={id=id,path=snapshot,source_path=path}
    storage.write_file(root..'/program-selection.json',json.encode(selected))
    cached={code=code,path=snapshot,state='checking'}
    validate_selected()
    return cached
end
-- Default selection is separate from the current/AI preview selection.
local boot_file=root..'/startup-program.json'
local function valid_path(path)
    return type(path)=='string' and path:sub(1,#dir+1)==dir..'/' and not path:find('..',1,true) and path:match('%.py$')
end
function M.default_program()
    local path=storage.exists(boot_file) and boot_file or boot_file..'.tmp'
    if not storage.exists(path) then return nil end
    local ok,value=pcall(function() return json.decode(storage.read_file(path)) end)
    if ok and type(value)=='table' and valid_path(value.path) then return value.path end
    return nil
end
function M.set_default(path)
    if path then
        assert(valid_path(path) and storage.exists(path),'program missing')
        limits.read_program(path)
        local ok,message,busy=runner.validate(path)
        assert(ok, busy and '解释器正忙，请稍后再试。' or '程序检查未通过。')
    end
    storage.write_file(boot_file..'.tmp',json.encode({path=path or false}))
    if storage.exists(boot_file) then storage.remove(boot_file) end
    storage.rename(boot_file..'.tmp',boot_file)
    return true
end
function M.list()
    if not storage.exists(dir) then storage.mkdir(dir) end
    local result={}
    for _,entry in ipairs(storage.listdir(dir)) do
        if #result>=limits.LIBRARY_ITEMS then break end
        if entry.type=='file' and entry.name:match('%.py$') and not entry.name:find('..',1,true) then
            local path=dir..'/'..entry.name
            local item={path=path,title=entry.name:sub(1,-4),origin='user'}
            if entry.name:match('^generated_') then item.title='AI 程序 '..string.format('%02d',#result+1);item.origin='ai' end
            if storage.exists(path..'.json') then
                local ok,meta=pcall(json.decode,storage.read_file(path..'.json'))
                if ok and type(meta)=='table' then item.title=meta.title or item.title;item.origin=meta.origin or 'user';item.id=meta.studio_id end
            end
            result[#result+1]=item
        end
    end
    table.sort(result,function(a,b) return a.path>b.path end)
    return result
end
M.read=limits.read_program
function M.select(path)
    assert(not job,'a program is running')
    assert(type(path)=='string' and path:sub(1,#dir+1)==dir..'/' and not path:find('..',1,true) and path:match('%.py$'),'invalid program path')
    local code=limits.read_program(path);assert(#code<=32768,'program too large')
    sequence=sequence+1
    selected={id=string.format('%x_%x',system.millis(),sequence),path=path}
    cached={path=path,code=code,state='checking'};last_answer=nil
    validate_selected()
    return cached.state=='ready',cached.state
end
function M.start(persistent)
    assert(selected and selected.validated and not job,'program not validated')
    if storage.exists(root..'/program-status.json') then storage.remove(root..'/program-status.json') end
    local ok,message=runner.start(persistent == true)
    assert(ok,message)
    job=assert(message:match('Started Python job (%x+)'),'missing program job id')
    last_job=job;last_result=nil
    return true
end
function M.current_path() return job and selected and selected.path end
function M.job_id() return job end
function M.forget(path) if selected and selected.path==path and not job then selected=nil;cached=nil;last_answer=nil end end
function M.status(id)
    assert(id==job or id==last_job,'unknown run')
    if job then return {state='running',output=''} end
    return last_result or {state='failed',error='result unavailable',output=''}
end
function M.running() return job~=nil end
function M.stop()
    if job then local ok,message=runner.stop();assert(ok,message) end
end
function M.tick()
    if system.millis()-last_poll<300 then return nil end
    last_poll=system.millis()
    if selected and cached and cached.state=='checking' then
        validate_selected()
        if cached.state=='checking' then return nil end
        return {state=cached.state=='ready' and 'validated' or 'validation_failed',code=cached.code,error=cached.error}
    end
    if not job then return nil end
    -- Wait until the native job terminates before allowing another run.
    local ok,list=runner.jobs();if not ok then return nil end
    local status=list:match(job..' | (%w+) |')
    if status=='running' or status=='queued' then return nil end
    if not status then return nil end
    local result={state=status,output=''}
    if storage.exists(root..'/program-status.json') then
        local parsed,value=pcall(json.decode,storage.read_file(root..'/program-status.json'))
        if parsed and value.id==selected.id then result=value end
    end
    if status=='timeout' or status=='stopped' or result.state=='running' then result.state=status end
    last_result=result;job=nil
    return result
end
return M
