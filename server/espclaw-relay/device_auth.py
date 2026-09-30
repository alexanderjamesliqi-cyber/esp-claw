"""Factory certificate + single-use possession proof. No device enrollment."""
import base64
import hashlib
import json
import re
import secrets
import time
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature


def certificate_message(device_id, key):
    der=key.public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
    return f'SPARK-CERT-V1\nspark.mpython.cn\n{device_id}\n{base64.b64encode(der).decode()}'.encode()


def factory_identity(payload, trust):
    device_id=payload.get('deviceId');pem=payload.get('publicKey');certificate=payload.get('certificate')
    if not isinstance(device_id,str) or not re.fullmatch('[a-f0-9]{12}',device_id) or not isinstance(pem,str) or len(pem)>1024 or not isinstance(certificate,str) or len(certificate)!=88:raise ValueError('Invalid certificate')
    if device_id in trust['revoked']:raise ValueError('Blocked device')
    key=serialization.load_pem_public_key(pem.encode())
    if not isinstance(key,ec.EllipticCurvePublicKey) or not isinstance(key.curve,ec.SECP256R1):raise ValueError('Wrong curve')
    raw=base64.b64decode(certificate,validate=True)
    if len(raw)!=64:raise ValueError('Wrong certificate length')
    signature=encode_dss_signature(int.from_bytes(raw[:32],'big'),int.from_bytes(raw[32:],'big'))
    message=certificate_message(device_id,key)
    for pem in trust['authorities']:
        try:
            root=serialization.load_pem_public_key(pem.encode())
            if not isinstance(root,ec.EllipticCurvePublicKey) or not isinstance(root.curve,ec.SECP256R1):continue
            root.verify(signature,message,ec.ECDSA(hashes.SHA256()))
            return key
        except Exception:continue
    raise ValueError('Untrusted certificate')


class DeviceSignatures:
    def __init__(self, registry, now=time.time):
        self.registry,self.now,self.pending=registry,now,{}

    async def is_blocked(self, device_id):
        return device_id in (await self.registry())['revoked']

    async def challenge(self, payload):
        digest=payload.get('requestHash')
        if not isinstance(digest,str) or not re.fullmatch('[a-f0-9]{64}',digest):raise ValueError('Invalid challenge')
        key=factory_identity(payload,await self.registry());device_id=payload['deviceId'];now=self.now()
        self.pending={k:v for k,v in self.pending.items() if v['expiresAt']>now*1000}
        if len(self.pending)>=500 or sum(c['deviceId']==device_id for c in self.pending.values())>=8:raise ValueError('Too many pending challenges')
        ident,nonce,expires=secrets.token_hex(16),secrets.token_hex(32),int(now*1000)+30000
        message=f'SPARK-AI-V1\nspark.mpython.cn\n{device_id}\n{ident}\n{nonce}\n{digest}\n{expires}'
        self.pending[ident]=dict(deviceId=device_id,requestHash=digest,expiresAt=expires,message=message,key=key)
        return dict(id=ident,message=message,expiresAt=expires)

    async def authenticate(self, authorization, digest):
        try:
            if not authorization or len(authorization)>2048 or not authorization.startswith('Bearer '):return None
            proof=json.loads(base64.b64decode(authorization[7:],validate=True))
            challenge=self.pending.pop(proof['challengeId'],None)
            if not challenge or challenge['expiresAt']<=self.now()*1000 or challenge['deviceId']!=proof['deviceId'] or challenge['requestHash']!=digest or await self.is_blocked(proof['deviceId']):return None
            challenge['key'].verify(base64.b64decode(proof['signature'],validate=True),challenge['message'].encode(),ec.ECDSA(hashes.SHA256()))
            return proof['deviceId']
        except Exception:return None


def realtime_hash(model):return hashlib.sha256(('realtime:'+model).encode()).hexdigest()
