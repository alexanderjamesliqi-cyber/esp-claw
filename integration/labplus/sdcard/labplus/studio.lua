-- Executed only by claw_bridge's UI service. No second program owner is created.
local fs=require('storage')
local json=require('json')
local system=require('system')
local root=fs.join_path(fs.get_root_dir(),'labplus')
local dir=fs.join_path(fs.get_root_dir(),'programs')
local limits=dofile(root..'/limits.lua')
local M={}
local alphabet='ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
local function encode(data)
 local out={}
 for i=1,#data,3 do
  local a,b,c=data:byte(i,i+2);local n=(a<<16)|((b or 0)<<8)|(c or 0)
  out[#out+1]=alphabet:sub((n>>18)+1,(n>>18)+1)..alphabet:sub(((n>>12)&63)+1,((n>>12)&63)+1)..(b and alphabet:sub(((n>>6)&63)+1,((n>>6)&63)+1) or '=')..(c and alphabet:sub((n&63)+1,(n&63)+1) or '=')
 end
 return table.concat(out)
end
local function decode(data)
 assert(type(data)=='string' and #data<=256 and #data%4==0 and not data:find('[^%w+/=]'),'invalid upload data')
 local out={}
 for i=1,#data,4 do
  local n=0
  for j=0,3 do local ch=data:sub(i+j,i+j);local index=alphabet:find(ch,1,true);assert(index or ch=='=','invalid base64');n=(n<<6)|((index or 1)-1) end
  out[#out+1]=string.char((n>>16)&255)
  if data:sub(i+2,i+2)~='=' then out[#out+1]=string.char((n>>8)&255) end
  if data:sub(i+3,i+3)~='=' then out[#out+1]=string.char(n&255) end
 end
 local value=table.concat(out);assert(encode(value)==data,'invalid base64 padding');return value
end
local function write(path,data) assert(fs.write_file(path,data),'storage write failed') end
local function remove(path) if fs.exists(path) then assert(fs.remove(path),'storage remove failed') end end
local function move(a,b) assert(fs.rename(a,b),'storage rename failed') end
local function read_json(path) return json.decode(fs.read_file(path)) end
local function title(value)
 assert(type(value)=='string','missing program title')
 value=value:match('^%s*(.-)%s*$')
 local count=utf8.len(value)
 assert(count and count>=1 and count<=60 and #value<=180 and not value:find('[%z\1-\31\127]'),'程序名称需为 1–60 个字符')
 return value
end
local function id(value) assert(type(value)=='string' and #value<=80 and value:match('^[%w_-]+$'),'invalid id');return value end
local function integer(value,low,high) assert(type(value)=='number' and value%1==0 and value>=low and value<=high,'invalid range');return value end
local journal=root..'/studio-transaction.json'
-- Journal enables rollback after failed writes or power loss, before accepting commands.
local function recover()
 if not fs.exists(journal) then return end
 local ops=read_json(journal)
 for i=#ops,1,-1 do
  local op=ops[i]
  if fs.exists(op.backup) then remove(op.path);move(op.backup,op.path)
  elseif not op.existed and op.source and not fs.exists(op.source) then remove(op.path) end
 end
 remove(journal)
end
local function transaction(ops)
 for _,op in ipairs(ops) do op.existed=fs.exists(op.path);op.backup=op.path..'.studio-old';remove(op.backup) end
 write(journal..'.tmp',json.encode(ops));move(journal..'.tmp',journal)
 local ok,err=pcall(function()
  for _,op in ipairs(ops) do
   if op.existed then move(op.path,op.backup) end
   if op.source then move(op.source,op.path) end
  end
 end)
 if not ok then recover();error(err) end
 remove(journal) -- commit point; obsolete backups can now be discarded
 for _,op in ipairs(ops) do pcall(remove,op.backup) end
end
local function metadata(item)
 return {title=item.title,origin=item.origin or 'user',studio_id=item.id}
end
function M.new(programs,ui,start)
 recover()
 -- A request from a previous boot has no live caller; never execute it later.
 remove(root..'/studio-request.json');remove(root..'/studio-response.json')
 if not fs.exists(dir) then assert(fs.mkdir(dir)) end
 local staging=nil;local revision=0;local counter=0
 local function unique(prefix) counter=counter+1;return string.format('%s_%x_%x_%x',prefix,system.millis(),counter,math.random(0,0x7fffffff)) end
 local function list()
  local items=programs.list();local ids={}
  for _,item in ipairs(items) do
   if type(item.id)~='string' or #item.id>80 or not item.id:match('^[%w_-]+$') or ids[item.id] then
    repeat item.id=unique('p') until not ids[item.id]
    local path=item.path..'.json';write(path..'.studio-new',json.encode(metadata(item)))
    transaction({{path=path,source=path..'.studio-new'}})
   end
   ids[item.id]=true;item.running=programs.current_path()==item.path;item.isDefault=programs.default_program()==item.path
  end
  return items
 end
 local function find(key)
  id(key);for _,item in ipairs(list()) do if item.id==key then return item end end
  error('程序不存在，请刷新列表')
 end
 local function available(item) assert(not item.running,'程序运行中，请先在设备上退出') end
 local function free_title(value,except)
  for _,item in ipairs(list()) do assert(item.title~=value or item.id==except,'名称已存在，请使用其他名称') end
 end
 local function public(item) return {id=item.id,title=item.title,origin=item.origin,running=item.running or false,isDefault=item.isDefault or false} end
 local function changed(path)
  revision=revision+1;programs.forget(path)
  local page=ui.product_status().page
  if page=='library' or page=='detail' or page=='startup' then ui.navigate('library') end
 end
 local function cleanup()
  if staging then remove(staging.path);staging=nil end
 end
 -- Only our abandoned staging files, never user .py programs, are reclaimed.
 for _,entry in ipairs(fs.listdir(dir)) do if entry.name:match('^studio_upload_[%w_]+%.part$') then remove(dir..'/'..entry.name) end end
 local function dispatch(op,a)
  assert(type(a)=='table','missing arguments')
  if op=='hello' then return {protocol=1,maxProgramBytes=limits.PROGRAM_BYTES} end
  if op=='list' then
   local offset=0
   if a.cursor and a.cursor~=json.null then
    local rev,pos=tostring(a.cursor):match('^(%d+):(%d+)$');assert(tonumber(rev)==revision and pos,'列表已变化，请刷新');offset=tonumber(pos)
   end
   local limit=integer(a.limit or 8,1,8);local items=list();assert(offset<=#items,'invalid cursor')
   local result={programs={}}
   for i=offset+1,math.min(offset+limit,#items) do result.programs[#result.programs+1]=public(items[i]) end
   if offset+limit<#items then result.nextCursor=string.format('%d:%d',revision,offset+limit) end
   return result
  end
  if op=='rename' or op=='delete' then
   local item=find(a.id);available(item)
   if op=='rename' then
    item.title=title(a.title);free_title(item.title,item.id)
    local path=item.path..'.json';write(path..'.studio-new',json.encode(metadata(item)));transaction({{path=path,source=path..'.studio-new'}})
    changed(item.path);return public(item)
   end
   local ops={{path=item.path},{path=item.path..'.json'}}
   if item.isDefault then ops[#ops+1]={path=root..'/startup-program.json'};ops[#ops+1]={path=root..'/startup-program.json.tmp'} end
   transaction(ops);changed(item.path);return {deleted=true}
  end
  if op=='upload.begin' then
   local name=title(a.title);local size=integer(a.size,1,limits.PROGRAM_BYTES);free_title(name,a.replaceId)
   local existing=a.replaceId and find(a.replaceId);if existing then available(existing) end
   assert(existing or #list()<limits.LIBRARY_ITEMS,'程序库已满')
   cleanup();local token=unique('u');local path=dir..'/studio_upload_'..token..'.part'
   write(path,'');staging={id=token,path=path,title=name,size=size,origin=a.origin=='ai' and 'ai' or 'user',replaceId=a.replaceId,offset=0,checked=0,at=system.millis()}
   return {uploadId=token}
  end
  if op:match('^upload%.') then
   assert(staging and id(a.uploadId)==staging.id,'上传会话已失效');staging.at=system.millis()
   if op=='upload.write' then
    assert(a.offset==staging.offset,'上传偏移不一致');local data=decode(a.data)
    assert(#data>0 and staging.offset+#data<=staging.size,'upload size mismatch')
    local file=assert(io.open(staging.path,'ab'));local ok=file:write(data);local closed=file:close();assert(ok and closed,'upload write failed')
    staging.offset=staging.offset+#data;return {offset=staging.offset}
   elseif op=='upload.read' then
    local offset=integer(a.offset,0,staging.size);local length=integer(a.length,1,192)
    assert(staging.offset==staging.size and offset==staging.checked and offset+length<=staging.size,'invalid verification range')
    local file=assert(io.open(staging.path,'rb'));file:seek('set',offset);local data=file:read(length);file:close();assert(data and #data==length,'read-back failed')
    staging.checked=offset+length;return {data=encode(data)}
   elseif op=='upload.commit' then
    assert(staging.offset==staging.size and staging.checked==staging.size,'program is not completely verified')
    local item=staging.replaceId and find(staging.replaceId);if item then available(item) end
    free_title(staging.title,staging.replaceId)
    item=item or {id=unique('p'),path=dir..'/studio_'..unique('p')..'.py'}
    item.title=staging.title;item.origin=staging.origin
    write(item.path..'.json.studio-new',json.encode(metadata(item)))
    transaction({{path=item.path,source=staging.path},{path=item.path..'.json',source=item.path..'.json.studio-new'}})
    staging=nil;changed(item.path);return public(item)
   end
  end
  if op=='run' then
   local item=find(a.id);assert(not programs.running(),'已有程序正在运行')
   assert(programs.select(item.path),'程序校验未完成或失败，请稍后重试')
   assert(start(),'程序无法启动');return {runId=programs.job_id()}
  elseif op=='status' then
   local current=programs.status(id(a.runId))
   local result={state=current.state,overflow=current.overflow or false}
   -- Bound the serialized reply as well as the captured text (control bytes escape).
   for _,key in ipairs({'output','error'}) do
    local value=tostring(current[key] or '')
    local budget=key=='output' and 8000 or 2000
    while #json.encode(value)>budget do
     local finish=#value//2
     while finish>0 and value:byte(finish+1)>=128 and value:byte(finish+1)<192 do finish=finish-1 end
     value=value:sub(1,finish);result.overflow=true
    end
    result[key]=value
   end
   return result
  elseif op=='stop' then programs.stop();return {stopped=true} end
  error('unsupported studio operation')
 end
 local service={}
 local function tick()
  if staging and system.millis()-staging.at>120000 then cleanup() end
  local path=root..'/studio-request.json'
  if not fs.exists(path) then return end
  local req=read_json(path)
  -- Consume before dispatch: a failed response write must never replay a mutation.
  remove(path)
  local ok,result=pcall(function()
   assert(req.v==1 and type(req.id)=='string' and #req.id<=80 and type(req.op)=='string','invalid studio envelope')
   return dispatch(req.op,req.args)
  end)
  local response={v=1,id=req.id,ok=ok}
  if ok then response.result=result else response.error=tostring(result) end
  local data=json.encode(response):gsub('"programs"%s*:%s*{}','"programs":[]')
  write(root..'/studio-response.tmp',data)
  move(root..'/studio-response.tmp',root..'/studio-response.json')
 end
 function service.tick()
  local ok,err=pcall(tick)
  if not ok then print('STUDIO_IO_ERROR '..tostring(err)) end
 end
 service.dispatch=dispatch -- shared by host-side tests; runtime accepts only envelopes
 return service
end
return M
