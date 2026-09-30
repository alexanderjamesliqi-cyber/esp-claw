import asyncio
import base64
import hashlib
import json
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from device_auth import DeviceSignatures, realtime_hash


def test_factory_signatures_and_replay():
    async def run():
        key=ec.generate_private_key(ec.SECP256R1());device_id='aabbccddeeff'
        device=dict(enabled=True,publicKey=key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode())
        async def registry():return {device_id:device}
        clock=[100.0];auth=DeviceSignatures(registry,now=lambda:clock[0]);digest=hashlib.sha256(b'hello').hexdigest()
        async def challenge():return await auth.challenge(dict(deviceId=device_id,requestHash=digest))
        def token(c):return 'Bearer '+base64.b64encode(json.dumps(dict(deviceId=device_id,challengeId=c['id'],signature=base64.b64encode(key.sign(c['message'].encode(),ec.ECDSA(hashes.SHA256()))).decode())).encode()).decode()
        c=await challenge();proof=token(c)
        assert await auth.authenticate(proof,digest)==device_id
        assert await auth.authenticate(proof,digest) is None
        c=await challenge();assert await auth.authenticate(token(c),'0'*64) is None
        c=await challenge();clock[0]+=31;assert await auth.authenticate(token(c),digest) is None
        c=await challenge();device['enabled']=False;assert await auth.authenticate(token(c),digest) is None
        assert await auth.authenticate('Bearer '+('x'*4096),digest) is None
        assert realtime_hash('qwen')==hashlib.sha256(b'realtime:qwen').hexdigest()
    asyncio.run(run())
