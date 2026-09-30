"""Update only the running app partition, preserving eFuse, NVS and user files."""
import argparse,base64,hashlib,json,struct,subprocess,sys,time
from pathlib import Path
from device import Device


def studio(device,op):
    ident='update-'+str(time.time_ns())
    request=base64.b64encode(json.dumps({'v':1,'id':ident,'op':op,'args':{}},separators=(',',':')).encode()).decode()
    reply=device.command('studio '+request)
    for line in reply.splitlines():
        if line.startswith('SPARK_STUDIO:'):
            value=json.loads(base64.b64decode(line[len('SPARK_STUDIO:'):]))
            if value.get('id')==ident and value.get('ok'):return value['result']
    raise RuntimeError('未读取到当前固件身份和运行分区，停止；请使用配套正式固件。')


def validate_partition(table,offset,image_size):
    entries={}
    for pos in range(0,len(table)-31,32):
        magic,kind,subtype,address,size,label,flags=struct.unpack('<HBBII16sI',table[pos:pos+32])
        if magic!=0x50aa:break
        entries[address]=(kind,subtype,size,label.rstrip(b'\0'))
    if offset not in (0x20000,0x520000):raise ValueError('Unknown running partition')
    expected_subtype=0x10 if offset==0x20000 else 0x11
    if entries.get(offset,())[:3]!=(0,expected_subtype,0x500000):raise ValueError('Partition layout mismatch')
    if not 24<=image_size<=0x500000:raise ValueError('Firmware does not fit app partition')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port',required=True)
    p.add_argument('--firmware',required=True,type=Path)
    p.add_argument('--sha256',required=True,help='发布包 manifest.json 中 edge_agent.bin 的校验值')
    p.add_argument('--backup-dir',type=Path,default=Path.home()/'spark-device-backups')
    a=p.parse_args()
    image=a.firmware.read_bytes()
    if hashlib.sha256(image).hexdigest()!=a.sha256.lower() or image[:1]!=b'\xe9':raise RuntimeError('固件校验失败。')
    device=Device(a.port)
    try:before=studio(device,'auth.info')
    finally:device.close()
    offset=before.get('appPartitionOffset')
    if offset not in (0x20000,0x520000):raise RuntimeError('未知的运行分区；不写入。')
    out=a.backup_dir/(before['deviceId']+'-'+time.strftime('%Y%m%d-%H%M%S'))
    out.mkdir(parents=True,exist_ok=False)
    # Keep backups private because Flash can contain Wi-Fi and user settings.
    out.chmod(0o700)
    def tool(*args,after='no-reset'):
        subprocess.run([sys.executable,'-m','esptool','--chip','esp32p4','--port',a.port,'--after',after,*map(str,args)],check=True)
    tool('read-flash','0x9000','0x1000',out/'partition-table.bin')
    validate_partition((out/'partition-table.bin').read_bytes(),offset,len(image))
    tool('read-flash',hex(offset),'0x500000',out/'previous-app.bin')
    (out/'identity.json').write_text(json.dumps(before,indent=2))
    tool('write-flash',hex(offset),a.firmware,after='hard-reset')
    time.sleep(3)
    device=Device(a.port)
    try:after=studio(device,'auth.info')
    finally:device.close()
    if (after['deviceId'],after['publicKey'])!=(before['deviceId'],before['publicKey']):raise RuntimeError('升级后身份校验失败，请保留备份并检查。')
    print('PASS: 应用已更新，设备身份一致；NVS、OTA 元数据、storage 和 eFuse 未写入。')
    print('原应用备份：'+str(out))

if __name__=='__main__':main()
