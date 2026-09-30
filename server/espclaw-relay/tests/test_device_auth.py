import asyncio
import base64
import hashlib
import json
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from device_auth import certificate_message
from device_auth import DeviceSignatures, realtime_hash


def test_factory_signatures_and_replay():
    async def run():
        key=ec.generate_private_key(ec.SECP256R1());device_id='aabbccddeeff'
        ca=ec.generate_private_key(ec.SECP256R1())
        public=key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        r,s=decode_dss_signature(ca.sign(certificate_message(device_id,key.public_key()),ec.ECDSA(hashes.SHA256())))
        device=dict(deviceId=device_id,publicKey=public,certificate=base64.b64encode(r.to_bytes(32,'big')+s.to_bytes(32,'big')).decode())
        trust=dict(authorities=[ca.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode()],revoked=[])
        async def registry():return trust
        clock=[100.0];auth=DeviceSignatures(registry,now=lambda:clock[0]);digest=hashlib.sha256(b'hello').hexdigest()
        async def challenge():return await auth.challenge(dict(**device,requestHash=digest))
        def token(c):return 'Bearer '+base64.b64encode(json.dumps(dict(deviceId=device_id,challengeId=c['id'],signature=base64.b64encode(key.sign(c['message'].encode(),ec.ECDSA(hashes.SHA256()))).decode())).encode()).decode()
        c=await challenge();proof=token(c)
        assert await auth.authenticate(proof,digest)==device_id
        assert await auth.authenticate(proof,digest) is None
        # A copied certificate does not prove possession of the certified key.
        attacker=ec.generate_private_key(ec.SECP256R1())
        c=await challenge()
        fake='Bearer '+base64.b64encode(json.dumps(dict(deviceId=device_id,challengeId=c['id'],signature=base64.b64encode(attacker.sign(c['message'].encode(),ec.ECDSA(hashes.SHA256()))).decode())).encode()).decode()
        assert await auth.authenticate(fake,digest) is None
        attacker_public=attacker.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        r,s=decode_dss_signature(attacker.sign(certificate_message(device_id,attacker.public_key()),ec.ECDSA(hashes.SHA256())))
        self_signed=base64.b64encode(r.to_bytes(32,'big')+s.to_bytes(32,'big')).decode()
        for changed in [dict(deviceId='001122334455'),dict(publicKey=attacker_public),dict(publicKey=attacker_public,certificate=self_signed)]:
            with pytest.raises(ValueError):
                await auth.challenge(dict(device,requestHash=digest,**changed))
        c=await challenge();assert await auth.authenticate(token(c),'0'*64) is None
        c=await challenge();clock[0]+=31;assert await auth.authenticate(token(c),digest) is None
        c=await challenge();trust['revoked'].append(device_id);assert await auth.authenticate(token(c),digest) is None
        assert await auth.authenticate('Bearer '+('x'*4096),digest) is None
        assert realtime_hash('qwen')==hashlib.sha256(b'realtime:qwen').hexdigest()
    asyncio.run(run())
