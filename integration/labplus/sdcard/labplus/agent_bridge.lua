-- Asynchronous access to the existing ESP-Claw event router; never blocks audio/UI.
local storage=require('storage')
local json=require('json')
local system=require('system')
local publisher=require('event_publisher')
local root=storage.join_path(storage.get_root_dir(),'.mpy_claw')
local lab=storage.join_path(storage.get_root_dir(),'labplus')
local M={};local sequence=0
function M.context(prompt)
    return storage.read_file(lab..'/board_context.md')..'\n'..prompt
end
function M.start(prompt)
    assert(type(prompt)=='string' and #prompt>0 and #prompt<=8000,'invalid agent prompt')
    sequence=sequence+1
    local id=string.format('%x_%x',system.millis(),sequence+0x100000)
    local folder=root..'/'..id
    assert(not storage.exists(folder),'agent request collision')
    storage.mkdir(folder)
    publisher.publish({source_cap='micropython_bridge',event_type='mpy_request',
      event_id='voice-'..id,source_channel='micropython',target_channel='micropython',
      chat_id=id,message_id=id,content_type='text',text=M.context(prompt),session_policy='nosave'})
    return {id=id,folder=folder,started=system.millis()}
end
function M.poll(job)
    local path=job.folder..'/status.json'
    if storage.exists(path) then
        local status=json.decode(storage.read_file(path))
        assert(status.id==job.id,'agent response mismatch')
        local answer=storage.read_file(job.folder..'/answer.txt')
        for _,f in ipairs({'answer.txt','status.json','status.tmp'}) do
            if storage.exists(job.folder..'/'..f) then storage.remove(job.folder..'/'..f) end
        end
        pcall(storage.remove,job.folder)
        return true,{ok=status.status=='ok',answer=answer}
    end
    if system.millis()-job.started>120000 then
        -- Don't remove a pending directory: an agent may still finish writing its result.
        return true,{ok=false,answer='设备任务暂未完成，请稍后查看。不要重复执行同一操作。'}
    end
    return false
end
return M
