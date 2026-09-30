import base64,hashlib,json
from dataclasses import replace
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from device_auth import certificate_message
import httpx
from starlette.testclient import TestClient
from relay import Settings,create_app


def test_factory_registry_gates_actual_routes():
    key=ec.generate_private_key(ec.SECP256R1());device_id='123456abcdef'
    ca=ec.generate_private_key(ec.SECP256R1())
    public=key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    r,s=decode_dss_signature(ca.sign(certificate_message(device_id,key.public_key()),ec.ECDSA(hashes.SHA256())))
    device=dict(deviceId=device_id,publicKey=public,certificate=base64.b64encode(r.to_bytes(32,'big')+s.to_bytes(32,'big')).decode())
    trust=dict(authorities=[ca.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode()],revoked=[])
    calls=[]
    def upstream(request):
        if request.url.host=='127.0.0.1':return httpx.Response(200,json=trust)
        calls.append(request);return httpx.Response(200,json={'choices':[{'message':{'content':'ok'}}]})
    config=Settings(cloud_key='cloud-secret',device_tokens={},device_registry_url='http://127.0.0.1:3000/internal/device-keys',realtime_url='wss://example.com/realtime')
    app=create_app(config,http_transport=httpx.MockTransport(upstream))
    with TestClient(app) as c:
        body=json.dumps({'model':'qwen-plus','messages':[{'role':'user','content':'test'}]},separators=(',',':'))
        digest=hashlib.sha256(body.encode()).hexdigest()
        def proof():
            r=c.post('/v1/auth/challenge',json={**device,'requestHash':digest});assert r.status_code==200
            challenge=r.json();signature=base64.b64encode(key.sign(challenge['message'].encode(),ec.ECDSA(hashes.SHA256()))).decode()
            token=base64.b64encode(json.dumps(dict(deviceId=device_id,challengeId=challenge['id'],signature=signature)).encode()).decode()
            return {'Authorization':'Bearer '+token,'X-Spark-Request-Hash':digest,'Content-Type':'application/json'}
        assert c.post('/v1/chat/completions',content=body).status_code==401
        assert c.post('/v1/auth/challenge',json={'deviceId':'eeeeeeeeeeee','requestHash':digest}).status_code==403
        headers=proof();assert c.post('/v1/chat/completions',content=body,headers=headers).status_code==200
        assert len(calls)==1 and calls[0].headers['authorization']=='Bearer cloud-secret'
        assert c.post('/v1/chat/completions',content=body,headers=headers).status_code==401
        headers=proof();assert c.post('/v1/chat/completions',content=body+' ',headers=headers).status_code==403
        headers=proof();trust['revoked'].append(device_id)
        assert c.post('/v1/chat/completions',content=body,headers=headers).status_code==401
        assert len(calls)==1
