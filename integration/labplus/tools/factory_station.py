"""Factory station: private key generation stays on the device. No key export."""
import argparse,base64,getpass,hashlib,json,re,secrets,time
from pathlib import Path
import serial
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

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
    p.add_argument('--device',required=True,help='现场工单上的 12 位小写 MAC')
    p.add_argument('--issuer-key',required=True,type=Path,help='工厂本地签发私钥，不上传服务器')
    p.add_argument('--records',type=Path,default=Path.home()/'spark-factory-records')
    p.add_argument('--resume',action='store_true',help='恢复未完成的工厂流程；不重新生成私钥')
    a=p.parse_args()
    if not re.fullmatch('[a-f0-9]{12}',a.device):p.error('Invalid device ID')
    raw=a.issuer_key.read_bytes()
    try:issuer=serialization.load_pem_private_key(raw,password=None)
    except TypeError:issuer=serialization.load_pem_private_key(raw,password=getpass.getpass('工厂签发密钥口令：').encode())
    if not isinstance(issuer,ec.EllipticCurvePrivateKey) or not isinstance(issuer.curve,ec.SECP256R1):raise ValueError('Expected a P-256 issuing key')
    console=Console(a.port)
    try:
        status=console.command('identity')
        match=re.search(r'DEVICE:([a-f0-9]{12}) REV:(\d+) KEY0_UNUSED:([01])',status)
        if not match or match[1]!=a.device or int(match[2])<300:raise RuntimeError('芯片版本/编号不匹配，停止。')
        if match[3]=='1':
            if a.resume:raise RuntimeError('设备尚未生成身份，不能恢复。')
            print('将为这台出厂设备永久写入 KEY0 私钥及 KEY1/KEY2 证书：'+a.device)
            if input('输入该设备编号确认：').strip()!=a.device:raise RuntimeError('未确认；没有写入。')
            status=console.command('provision '+a.device+' CONFIRM_EFUSE')
        info=console.record(status)
        device_key=serialization.load_pem_public_key(info['publicKey'].encode())
        der=device_key.public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
        message=f"SPARK-CERT-V1\nspark.mpython.cn\n{a.device}\n{base64.b64encode(der).decode()}".encode()
        if 'certificate' not in info:
            r,s=decode_dss_signature(issuer.sign(message,ec.ECDSA(hashes.SHA256())))
            certificate=base64.b64encode(r.to_bytes(32,'big')+s.to_bytes(32,'big')).decode()
            info=console.record(console.command('attest '+certificate+' CONFIRM_CERT'))
            if info.get('certificate')!=certificate:raise RuntimeError('证书写入或回读失败；隔离设备。')
        else:
            from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
            cert=base64.b64decode(info['certificate'],validate=True)
            if len(cert)!=64:raise ValueError('Invalid certificate')
            issuer.public_key().verify(encode_dss_signature(int.from_bytes(cert[:32],'big'),int.from_bytes(cert[32:],'big')),message,ec.ECDSA(hashes.SHA256()))
        challenge=f"SPARK-AI-V1\nspark.mpython.cn\n{a.device}\n{secrets.token_hex(16)}\n{secrets.token_hex(32)}\n{hashlib.sha256(b'factory-proof').hexdigest()}\n{int(time.time()*1000)+30000}"
        verify_identity(info,console.sign(challenge),challenge)
        a.records.mkdir(parents=True,exist_ok=True);record=a.records/(a.device+'.json')
        if record.exists() and json.loads(record.read_text())['publicKey']!=info['publicKey']:raise RuntimeError('同一设备公钥变化，停止。')
        record.write_text(json.dumps(info,ensure_ascii=False,indent=2))
        print('PASS: 离线签发、证书回读、设备签名验证完成；无需服务器登记。')
        print('公钥及证书记录：'+str(record))
    finally:console.port.close()

if __name__=='__main__':main()
