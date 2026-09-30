"""Single-use P-256 challenges. Only factory-registered public keys are trusted."""
import base64
import hashlib
import json
import re
import secrets
import time
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec


class DeviceSignatures:
    def __init__(self, registry, now=time.time):
        self.registry, self.now, self.pending = registry, now, {}

    async def challenge(self, payload):
        device_id, digest = payload.get('deviceId'), payload.get('requestHash')
        if not isinstance(device_id, str) or not re.fullmatch('[a-f0-9]{12}', device_id) or not isinstance(digest, str) or not re.fullmatch('[a-f0-9]{64}', digest):
            raise ValueError('Invalid challenge')
        devices = await self.registry()
        device = devices.get(device_id)
        if not device or not device.get('enabled'):
            raise ValueError('Device is not factory authorized')
        now = self.now()
        self.pending = {k:v for k,v in self.pending.items() if v['expiresAt'] > now * 1000}
        if len(self.pending) >= 500 or sum(c['deviceId'] == device_id for c in self.pending.values()) >= 8:
            raise ValueError('Too many pending challenges')
        ident, nonce, expires = secrets.token_hex(16), secrets.token_hex(32), int(now*1000)+30000
        message = f'SPARK-AI-V1\nspark.mpython.cn\n{device_id}\n{ident}\n{nonce}\n{digest}\n{expires}'
        self.pending[ident] = dict(deviceId=device_id, requestHash=digest, expiresAt=expires, message=message, publicKey=device['publicKey'])
        return dict(id=ident, message=message, expiresAt=expires)

    async def authenticate(self, authorization, digest):
        try:
            if not authorization or len(authorization)>2048 or not authorization.startswith('Bearer '):
                return None
            proof=json.loads(base64.b64decode(authorization[7:],validate=True))
            challenge=self.pending.pop(proof['challengeId'],None)
            if not challenge or challenge['expiresAt'] <= self.now()*1000 or challenge['deviceId'] != proof['deviceId'] or challenge['requestHash'] != digest:
                return None
            device=(await self.registry()).get(proof['deviceId'])
            if not device or not device.get('enabled') or device['publicKey'] != challenge['publicKey']:
                return None
            key=serialization.load_pem_public_key(device['publicKey'].encode())
            if not isinstance(key,ec.EllipticCurvePublicKey) or not isinstance(key.curve,ec.SECP256R1):
                return None
            key.verify(base64.b64decode(proof['signature'],validate=True),challenge['message'].encode(),ec.ECDSA(hashes.SHA256()))
            return proof['deviceId']
        except Exception:
            return None


def realtime_hash(model):
    return hashlib.sha256(('realtime:'+model).encode()).hexdigest()
