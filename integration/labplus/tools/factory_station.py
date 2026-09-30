"""Factory station: private key generation stays on the device. No key export."""
import argparse,base64,getpass,hashlib,json,re,secrets,time
from pathlib import Path
import httpx
import serial
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import ec

ORIGIN='https://spark.mpython.cn'

class Console:
    def __init__(self,port):
        self.port=serial.Serial(port=None,baudrate=115200,timeout=.1)
        self.port.dtr=True;self.port.rts=False;self.port.port=port;self.port.open()
        self.port.write(b'\n');self.read_prompt()
    def read_prompt(self):
        data=bytearray();deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            data.extend(self.port.read(4096))
            if b'factory> ' in data:return data.decode(errors='replace').replace('\r','')
        raise RuntimeError('未检测到出厂固件 factory>，请先刷入出厂镜像。')
    def command(self,text):
        # Do not retry a burn automatically.
        self.port.write((text+'\n').encode());return self.read_prompt()
    def record(self,reply,prefix='SPARK_FACTORY:'):
        for line in reply.splitlines():
            if line.startswith(prefix):return json.loads(line[len(prefix):])
        raise RuntimeError('设备未返回受保护身份；请检查串口和 eFuse 状态。')
    def sign(self,message):
        reply=self.command('sign '+base64.b64encode(message.encode()).decode())
        return self.record(reply,'SPARK_PROOF:')

def verify_identity(info,proof,message):
    if info.get('algorithm')!='ECDSA-P256-SHA256' or info.get('efuseProtected') is not True or not re.fullmatch('[a-f0-9]{12}',info.get('deviceId','')) or proof.get('deviceId')!=info['deviceId']:
        raise ValueError('Invalid protected device identity')
    key=serialization.load_pem_public_key(info['publicKey'].encode())
    if not isinstance(key,ec.EllipticCurvePublicKey) or not isinstance(key.curve,ec.SECP256R1):raise ValueError('Wrong key curve')
    key.verify(base64.b64decode(proof['signature'],validate=True),message.encode(),ec.ECDSA(hashes.SHA256()))

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port',required=True)
    p.add_argument('--device',required=True,help='机身/工单上的 12 位小写 MAC；现场核对后才允许写入')
    p.add_argument('--label',default='')
    p.add_argument('--records',type=Path,default=Path.home()/'spark-factory-records')
    p.add_argument('--resume',action='store_true',help='读取已生成的相同身份并完成登记，不写 eFuse')
    a=p.parse_args()
    if not re.fullmatch('[a-f0-9]{12}',a.device):p.error('Invalid device ID')
    password=getpass.getpass('Spark 出厂管理员密码：')
    with httpx.Client(base_url=ORIGIN,timeout=20,follow_redirects=False,trust_env=False) as client:
        r=client.post('/api/admin/login',json={'password':password});password=None;r.raise_for_status()
        client.headers['Authorization']='Bearer '+r.json()['token']
        try:
            console=Console(a.port)
            try:
                status=console.command('identity')
                match=re.search(r'DEVICE:([a-f0-9]{12}) REV:(\d+) KEY0_UNUSED:([01])',status)
                if not match or match[1]!=a.device or int(match[2])<300:raise RuntimeError('芯片型号/版本/编号不匹配，停止。')
                if match[3]=='1':
                    if a.resume:raise RuntimeError('设备尚未生成身份，不能恢复登记。')
                    print('即将永久写入 KEY0，仅用于这一台出厂设备：'+a.device)
                    if input('输入该设备编号确认一次性写入：').strip()!=a.device:raise RuntimeError('未确认；没有写入。')
                    status=console.command('provision '+a.device+' CONFIRM_EFUSE')
                info=console.record(status)
                message=f"SPARK-AI-V1\nspark.mpython.cn\n{a.device}\n{secrets.token_hex(16)}\n{secrets.token_hex(32)}\n{hashlib.sha256(b'factory-proof').hexdigest()}\n{int(time.time()*1000)+30000}"
                verify_identity(info,console.sign(message),message)
                a.records.mkdir(parents=True,exist_ok=True)
                record=a.records/(a.device+'.json')
                if record.exists() and json.loads(record.read_text())['publicKey']!=info['publicKey']:raise RuntimeError('同一设备的公钥发生变化，停止登记。')
                record.write_text(json.dumps(info,ensure_ascii=False,indent=2))
                devices=client.get('/api/admin/devices');devices.raise_for_status()
                existing=next((d for d in devices.json()['devices'] if d['deviceId']==a.device),None)
                if existing and (existing['publicKey']!=info['publicKey'] or not existing['enabled']):raise RuntimeError('已有记录公钥不一致或已被吊销，需要管理员核查。')
                r=client.put('/api/admin/devices',json={'deviceId':a.device,'publicKey':info['publicKey'],'enabled':True,'label':a.label or a.device});r.raise_for_status()
                # Verify actual relay authorization without consuming model quota.
                challenge=client.post('/v1/auth/challenge',json={'deviceId':a.device,'requestHash':hashlib.sha256(b'models').hexdigest()});challenge.raise_for_status();challenge=challenge.json()
                proof=console.sign(challenge['message']);proof['challengeId']=challenge['id']
                bearer=base64.b64encode(json.dumps(proof,separators=(',',':')).encode()).decode()
                r=client.get('/v1/models',headers={'Authorization':'Bearer '+bearer});r.raise_for_status()
                print('PASS: 硬件签名、公钥登记、线上验签完成。公钥记录：'+str(record))
                print('现在刷入正式固件；以后升级不再运行出厂步骤。')
            finally:console.port.close()
        finally:client.post('/api/admin/logout',json={})

if __name__=='__main__':main()
