import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
import json

import httpx
import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from relay import Admission, Settings, create_app

TOKEN = 'test-device-token-' + 'x' * 32
CLOUD = 'fake-cloud-secret-for-unit-tests'
AUTH = {'Authorization': 'Bearer ' + TOKEN}
BODY = {'model': 'qwen-plus', 'messages': [{'role': 'user', 'content': 'hello'}]}


def config(**kwargs):
    return Settings(cloud_key=CLOUD, device_tokens={'board1': TOKEN},
                    realtime_url='wss://cloud.example/realtime', **kwargs)


def test_settings_fail_closed():
    with pytest.raises(ValueError):
        Settings.from_env()
    with pytest.raises(ValueError):
        replace(config(), device_tokens={'board': CLOUD})
    with pytest.raises(ValueError):
        replace(config(), http_base='http://cloud.example/v1')
    with pytest.raises(ValueError):
        replace(config(), realtime_url='wss://cloud.example/ws?key=bad')


def test_auth_and_forwarding():
    calls = []
    def upstream(request):
        calls.append(request)
        assert request.headers['authorization'] == 'Bearer ' + CLOUD
        assert 'x-device-private' not in request.headers
        assert json.loads(request.content) == BODY
        return httpx.Response(200, json={'choices': [{'message': {'content': 'hello'}}]})
    app = create_app(config(), http_transport=httpx.MockTransport(upstream))
    with TestClient(app) as client:
        assert client.get('/healthz').json() == {'status': 'ok'}
        assert client.get('/v1/models').status_code == 401
        assert client.post('/v1/chat/completions', json=BODY).status_code == 401
        assert not calls
        assert client.get('/v1/models', headers=AUTH).status_code == 200
        result = client.post('/v1/chat/completions', json=BODY, headers={**AUTH, 'x-device-private': 'hidden'})
        assert result.status_code == 200
        assert len(calls) == 1
        assert app.state.admission.active['http'] == 0


@pytest.mark.parametrize('body,status', [(b'bad', 400), (b'{}', 400),
    (json.dumps({**BODY, 'model': 'unapproved'}).encode(), 400),
    (json.dumps({**BODY, 'stream': 'yes'}).encode(), 400), (b'x' * 1025, 413)])
def test_invalid_request(body, status):
    def upstream(request):
        pytest.fail('invalid request reached cloud')
    app = create_app(config(max_body=1024), http_transport=httpx.MockTransport(upstream))
    with TestClient(app) as client:
        assert client.post('/v1/chat/completions', content=body, headers=AUTH).status_code == status
        assert app.state.admission.active['http'] == 0


@pytest.mark.parametrize('cloud_status,relay_status', [(401, 502), (429, 503), (302, 502)])
def test_provider_errors_hidden(cloud_status, relay_status):
    app = create_app(config(), http_transport=httpx.MockTransport(
        lambda r: httpx.Response(cloud_status, text=CLOUD)))
    with TestClient(app) as client:
        response = client.post('/v1/chat/completions', json=BODY, headers=AUTH)
        assert response.status_code == relay_status
        assert CLOUD not in response.text
        assert app.state.admission.active['http'] == 0


def test_http_timeout_and_limit():
    async def upstream(request):
        await asyncio.sleep(1)
    app = create_app(config(http_seconds=.02), http_transport=httpx.MockTransport(upstream))
    with TestClient(app) as client:
        assert client.post('/v1/chat/completions', json=BODY, headers=AUTH).status_code == 504
        assert app.state.admission.active['http'] == 0
    app = create_app(config(max_response=8), http_transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b'x' * 9)))
    with TestClient(app) as client:
        assert client.post('/v1/chat/completions', json=BODY, headers=AUTH).status_code == 502


class Stream(httpx.AsyncByteStream):
    closed = False
    async def __aiter__(self):
        yield b'data: {"choices":[{"delta":{"tool_calls":[]}}]}\n\n'
        yield b'data: [DONE]\n\n'
    async def aclose(self):
        self.closed = True


def test_sse_closes_and_releases():
    stream = Stream()
    app = create_app(config(), http_transport=httpx.MockTransport(lambda r: httpx.Response(
        200, stream=stream, headers={'content-type': 'text/event-stream'})))
    with TestClient(app) as client:
        result = client.post('/v1/chat/completions', json={**BODY, 'stream': True}, headers=AUTH)
        assert result.status_code == 200
        assert 'tool_calls' in result.text and '[DONE]' in result.text
        assert stream.closed
        assert app.state.admission.active['http'] == 0


def test_admission():
    limits = Admission(config(max_http=1, requests_per_minute=3))
    assert limits.authenticate('Bearer ' + TOKEN) == 'board1'
    assert limits.authenticate('Bearer bad') is None
    assert limits.acquire('http', 'board1')
    assert not limits.acquire('http', 'board1')
    limits.release('http', 'board1')
    assert limits.acquire('ws', 'board1')
    assert not limits.acquire('ws', 'board1')
    limits.release('ws', 'board1')
    assert limits.acquire('ws', 'board1')
    limits.release('ws', 'board1')
    assert not limits.acquire('http', 'board1')


class EchoCloud:
    def __init__(self):
        self.queue = asyncio.Queue()
    async def send(self, value):
        await self.queue.put(value)
    def __aiter__(self):
        return self
    async def __anext__(self):
        return await self.queue.get()


class Connector:
    def __init__(self, fail=False):
        self.calls = []
        self.closed = 0
        self.fail = fail
    @asynccontextmanager
    async def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.fail:
            raise RuntimeError(CLOUD)
        try:
            yield EchoCloud()
        finally:
            self.closed += 1


def test_websocket_auth_and_bidirectional():
    connector = Connector()
    app = create_app(config(), ws_connector=connector)
    with TestClient(app) as client:
        for url, headers in [('/v1/realtime', {}), ('/v1/realtime?model=bad', AUTH), ('/v1/realtime?url=https://evil.example', AUTH)]:
            with pytest.raises(WebSocketDisconnect):
                with client.websocket_connect(url, headers=headers):
                    pass
        assert not connector.calls
        with client.websocket_connect('/v1/realtime', headers=AUTH) as ws:
            for event in [{'type': 'response.cancel'}, {'type': 'input_audio_buffer.append', 'audio': 'AA=='},
                          {'type': 'conversation.item.create', 'item': {'type': 'function_call_output', 'output': 'ok'}}]:
                ws.send_json(event)
                assert ws.receive_json() == event
            ws.send_bytes(b'\x01\x02')
            assert ws.receive_bytes() == b'\x01\x02'
        assert connector.closed == 1
        assert connector.calls[0][1]['additional_headers'] == {'Authorization': 'Bearer ' + CLOUD}
        assert app.state.admission.active['ws'] == 0


@pytest.mark.parametrize('mode,code', [('size', 1009), ('timeout', 1001), ('upstream', 1011)])
def test_websocket_cleanup(mode, code):
    connector = Connector(fail=mode == 'upstream')
    app = create_app(config(max_frame=16, session_seconds=.05), ws_connector=connector)
    with TestClient(app) as client:
        with client.websocket_connect('/v1/realtime', headers=AUTH) as ws:
            if mode == 'size':
                ws.send_text('x' * 17)
            message = ws.receive()
            assert message['type'] == 'websocket.close'
            assert message['code'] == code
            assert CLOUD not in message.get('reason', '')
        assert app.state.admission.active['ws'] == 0
