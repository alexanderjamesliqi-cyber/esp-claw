local storage=require('storage');local json=require('json');local system=require('system');local delay=require('delay')
local id='faded20260928_1';local folder='/sdcard/.mpy_claw/'..id
if not storage.exists(folder) then storage.mkdir(folder) end
assert(not storage.exists(folder..'/request.json'),'previous request pending')
if storage.exists(folder..'/response.json') then storage.remove(folder..'/response.json') end
storage.write_file(folder..'/request.tmp',json.encode({id=id,name=args.n,payload=args.p or {}}))
storage.rename(folder..'/request.tmp',folder..'/request.json')
local start=system.millis()
while not storage.exists(folder..'/response.json') do
 assert(system.millis()-start<8000,'UI bridge unresponsive')
 delay.delay_ms(10)
end
local result=json.decode(storage.read_file(folder..'/response.json'));storage.remove(folder..'/response.json')
local response={ok=result.ok,output=result.output,latency_ms=system.millis()-start}
if not result.ok then response.error=result.error end
print('QA_RESULT '..json.encode(response))
