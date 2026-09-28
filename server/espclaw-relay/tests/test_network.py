"""Real TCP integration, with a local fake cloud and no paid API calls."""
import asyncio
from contextlib import asynccontextmanager
import socket

import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.responses import StreamingResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocketDisconnect
from websockets.asyncio.client import connect

from relay import Settings, create_app
from test_relay import TOKEN, CLOUD, AUTH, BODY


@asynccontextmanager
async def serving(app):
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    sock.listen(128)
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='error', access_log=False, timeout_graceful_shutdown=1))
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        async with asyncio.timeout(5):
            while not server.started:
                if task.done():
                    task.result()
                await asyncio.sleep(.01)
        yield port
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, 5)
        sock.close()


def test_real_network_disconnect_and_reconnect():
    async def scenario():
        stream_closed = asyncio.Event()
        ws_closed = asyncio.Event()

        async def chat(request):
            assert request.headers['authorization'] == 'Bearer ' + CLOUD
            async def data():
                try:
                    while True:
                        yield b'data: {"text":"hello"}\n\n'
                        await asyncio.sleep(.01)
                finally:
                    stream_closed.set()
            return StreamingResponse(data(), media_type='text/event-stream')

        async def voice(ws):
            assert ws.headers['authorization'] == 'Bearer ' + CLOUD
            await ws.accept()
            try:
                while True:
                    await ws.send_text(await ws.receive_text())
            except WebSocketDisconnect:
                pass
            finally:
                ws_closed.set()

        cloud = Starlette(routes=[Route('/v1/chat/completions', chat, methods=['POST']), WebSocketRoute('/realtime', voice)])
        async with serving(cloud) as cloud_port:
            cfg = Settings(cloud_key=CLOUD, device_tokens={'board1': TOKEN},
                           http_base=f'http://127.0.0.1:{cloud_port}/v1',
                           realtime_url=f'ws://127.0.0.1:{cloud_port}/realtime', allow_local_test_upstream=True)
            relay = create_app(cfg)
            async with serving(relay) as relay_port:
                async with httpx.AsyncClient(trust_env=False) as client:
                    async with client.stream('POST', f'http://127.0.0.1:{relay_port}/v1/chat/completions',
                                             headers=AUTH, json={**BODY, 'stream': True}) as response:
                        assert response.status_code == 200
                        async for line in response.aiter_lines():
                            assert 'hello' in line
                            break
                    await asyncio.wait_for(stream_closed.wait(), 2)
                for _ in range(3):
                    ws_closed.clear()
                    async with connect(f'ws://127.0.0.1:{relay_port}/v1/realtime', additional_headers=AUTH, proxy=None) as ws:
                        await ws.send('{"type":"response.cancel"}')
                        assert await ws.recv() == '{"type":"response.cancel"}'
                    await asyncio.wait_for(ws_closed.wait(), 2)
                    async with asyncio.timeout(2):
                        while relay.state.admission.active['ws']:
                            await asyncio.sleep(.01)
                assert relay.state.admission.active == {'http': 0, 'ws': 0}
    asyncio.run(scenario())
