"""Bounded HTTP/SSE and realtime WebSocket relay. Secrets come from the environment."""
from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
import hashlib
import hmac
import json
import logging
import os
import re
import time
from urllib.parse import urlencode, urlsplit

import anyio
import httpx
from starlette.applications import Starlette
from starlette.requests import ClientDisconnect, Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

LOG = logging.getLogger("espclaw.relay")


def _url(value: str, scheme: str, name: str, allow_local: bool) -> str:
    parsed = urlsplit(value)
    local = allow_local and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    allowed = {scheme, "http" if scheme == "https" else "ws"} if local else {scheme}
    if parsed.scheme not in allowed or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError(f"Invalid {name}; use a fixed TLS endpoint without credentials or query")
    return value.rstrip("/")


@dataclass(frozen=True)
class Settings:
    cloud_key: str = field(repr=False)
    device_tokens: dict[str, str] = field(repr=False)
    realtime_url: str
    http_base: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    text_models: tuple[str, ...] = ("qwen-plus",)
    realtime_models: tuple[str, ...] = ("qwen3.5-omni-flash-realtime",)
    max_http: int = 16
    max_ws: int = 16
    http_per_device: int = 2
    requests_per_minute: int = 60
    max_body: int = 1024 * 1024
    max_response: int = 16 * 1024 * 1024
    max_frame: int = 256 * 1024
    http_seconds: float = 120
    session_seconds: float = 900
    connect_seconds: float = 10
    allow_local_test_upstream: bool = False

    def __post_init__(self):
        if not self.cloud_key or any(c in self.cloud_key for c in "\r\n"):
            raise ValueError("CLOUD_API_KEY is required")
        if not 1 <= len(self.device_tokens) <= 256:
            raise ValueError("DEVICE_TOKENS_JSON must contain 1..256 devices")
        seen = set()
        for name, token in self.device_tokens.items():
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name) or not isinstance(token, str) or len(token) < 32 or token.startswith("replace-"):
                raise ValueError("Each device needs an identifier and a random token of at least 32 characters")
            if token == self.cloud_key or token in seen or any(c.isspace() for c in token):
                raise ValueError("Device tokens must be unique, whitespace-free and different from the cloud key")
            seen.add(token)
        object.__setattr__(self, "http_base", _url(self.http_base, "https", "CLOUD_HTTP_BASE", self.allow_local_test_upstream))
        object.__setattr__(self, "realtime_url", _url(self.realtime_url, "wss", "CLOUD_REALTIME_URL", self.allow_local_test_upstream))
        for models in (self.text_models, self.realtime_models):
            if not models or any(not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", m) for m in models):
                raise ValueError("Model allowlists must contain valid model identifiers")
        for name in ("max_http", "max_ws", "http_per_device", "requests_per_minute", "max_body", "max_response", "max_frame", "http_seconds", "session_seconds", "connect_seconds"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")

    @classmethod
    def from_env(cls):
        try:
            tokens = json.loads(os.environ.get("DEVICE_TOKENS_JSON", "{}"))
            if not isinstance(tokens, dict):
                raise ValueError()
        except (ValueError, TypeError):
            raise ValueError("DEVICE_TOKENS_JSON must be a JSON object") from None
        return cls(
            cloud_key=os.environ.get("CLOUD_API_KEY", ""),
            device_tokens=tokens,
            realtime_url=os.environ.get("CLOUD_REALTIME_URL", ""),
            http_base=os.environ.get("CLOUD_HTTP_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            text_models=tuple(x.strip() for x in os.environ.get("TEXT_MODELS", "qwen-plus").split(",") if x.strip()),
            realtime_models=tuple(x.strip() for x in os.environ.get("REALTIME_MODELS", "qwen3.5-omni-flash-realtime").split(",") if x.strip()),
            max_http=int(os.environ.get("MAX_HTTP_REQUESTS", "16")),
            max_ws=int(os.environ.get("MAX_REALTIME_SESSIONS", "16")),
            http_per_device=int(os.environ.get("HTTP_PER_DEVICE", "2")),
            requests_per_minute=int(os.environ.get("REQUESTS_PER_MINUTE", "60")),
            http_seconds=float(os.environ.get("HTTP_TIMEOUT_SECONDS", "120")),
            session_seconds=float(os.environ.get("REALTIME_SESSION_SECONDS", "900")),
        )


class Admission:
    """Event-loop-owned counters: no await between checking and taking a slot."""
    def __init__(self, settings: Settings):
        self.settings = settings
        self.active = {"http": 0, "ws": 0}
        self.devices = defaultdict(int)
        self.starts = defaultdict(deque)
        self.tokens = {hashlib.sha256(v.encode()).digest(): k for k, v in settings.device_tokens.items()}

    def authenticate(self, authorization: str | None) -> str | None:
        if not authorization or len(authorization) > 1024 or not authorization.startswith("Bearer "):
            return None
        digest = hashlib.sha256(authorization[7:].encode()).digest()
        identity = None
        for candidate, device in self.tokens.items():
            if hmac.compare_digest(digest, candidate):
                identity = device
        return identity

    def acquire(self, kind: str, device: str) -> bool:
        now = time.monotonic()
        times = self.starts[device]
        while times and times[0] <= now - 60:
            times.popleft()
        limit = self.settings.http_per_device if kind == "http" else 1
        total = self.settings.max_http if kind == "http" else self.settings.max_ws
        if len(times) >= self.settings.requests_per_minute or self.active[kind] >= total or self.devices[kind, device] >= limit:
            return False
        times.append(now)
        self.active[kind] += 1
        self.devices[kind, device] += 1
        return True

    def release(self, kind: str, device: str):
        self.active[kind] -= 1
        self.devices[kind, device] -= 1


def error(status: int, message: str):
    return JSONResponse({"error": {"message": message, "type": "relay_error"}}, status_code=status,
                        headers={"Cache-Control": "no-store"})


async def close_http(response: httpx.Response):
    # Starlette may cancel the request scope when the device disconnects.
    with anyio.CancelScope(shield=True):
        await response.aclose()


class OwnedStream(StreamingResponse):
    def __init__(self, upstream, admission, device, deadline, settings):
        self.upstream, self.admission, self.device = upstream, admission, device
        self.deadline, self.settings = deadline, settings
        super().__init__(self.chunks(), media_type="text/event-stream",
                         headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    async def chunks(self):
        total = 0
        try:
            async with asyncio.timeout_at(self.deadline):
                async for chunk in self.upstream.aiter_bytes():
                    total += len(chunk)
                    if total > self.settings.max_response:
                        raise ValueError("response limit")
                    yield chunk
        except (TimeoutError, httpx.HTTPError, ValueError):
            yield b'event: error\ndata: {"error":{"type":"relay_error","message":"Upstream stream interrupted"}}\n\n'

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            try:
                await close_http(self.upstream)
            finally:
                self.admission.release("http", self.device)


def create_app(settings: Settings | None = None, *, http_transport=None, ws_connector=connect):
    cfg = settings or Settings.from_env()
    admission = Admission(cfg)

    @asynccontextmanager
    async def lifespan(app):
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(cfg.http_seconds, connect=cfg.connect_seconds),
            limits=httpx.Limits(max_connections=cfg.max_http, max_keepalive_connections=cfg.max_http),
            transport=http_transport, follow_redirects=False, trust_env=False,
        ) as client:
            app.state.http = client
            yield

    async def health(request):
        return JSONResponse({"status": "ok"})

    async def models(request):
        if not admission.authenticate(request.headers.get("authorization")):
            return error(401, "Invalid device token")
        return JSONResponse({"object": "list", "data": [{"id": m, "object": "model"} for m in sorted(set(cfg.text_models + cfg.realtime_models))]})

    async def chat(request: Request):
        device = admission.authenticate(request.headers.get("authorization"))
        if not device:
            return error(401, "Invalid device token")
        if not admission.acquire("http", device):
            return error(429, "Request capacity reached; retry later")
        transferred = False
        upstream = None
        deadline = asyncio.get_running_loop().time() + cfg.http_seconds
        try:
            raw = bytearray()
            async with asyncio.timeout(min(15, cfg.http_seconds)):
                async for chunk in request.stream():
                    raw.extend(chunk)
                    if len(raw) > cfg.max_body:
                        return error(413, "Request body too large")
            try:
                payload = json.loads(raw)
            except (ValueError, UnicodeError):
                return error(400, "Invalid JSON")
            if not isinstance(payload, dict) or payload.get("model") not in cfg.text_models:
                return error(400, "Model is not enabled")
            if not isinstance(payload.get("messages"), list) or not payload["messages"] or not isinstance(payload.get("stream", False), bool):
                return error(400, "messages must be a nonempty array and stream must be boolean")
            async with asyncio.timeout_at(deadline):
                outgoing = request.app.state.http.build_request(
                    "POST", cfg.http_base + "/chat/completions", json=payload,
                    headers={"Authorization": "Bearer " + cfg.cloud_key, "Accept-Encoding": "identity"},
                )
                upstream = await request.app.state.http.send(outgoing, stream=True)
                if upstream.status_code != 200:
                    # Don't expose provider error bodies, request headers or keys.
                    return error(503 if upstream.status_code == 429 else 502, "Cloud service rejected the request")
                if payload.get("stream"):
                    if "text/event-stream" not in upstream.headers.get("content-type", ""):
                        return error(502, "Cloud service returned an unexpected stream")
                    response = OwnedStream(upstream, admission, device, deadline, cfg)
                    transferred = True
                    return response
                data = bytearray()
                async for chunk in upstream.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > cfg.max_response:
                        return error(502, "Cloud response too large")
                return Response(bytes(data), media_type="application/json", headers={"Cache-Control": "no-store"})
        except (TimeoutError, httpx.TimeoutException):
            return error(504, "Cloud request timed out")
        except httpx.HTTPError:
            return error(502, "Cloud connection failed")
        except ClientDisconnect:
            return error(400, "Device disconnected")
        finally:
            if not transferred:
                try:
                    if upstream is not None:
                        await close_http(upstream)
                finally:
                    admission.release("http", device)

    async def realtime(ws: WebSocket):
        device = admission.authenticate(ws.headers.get("authorization"))
        if not device:
            await ws.close(code=1008)  # Before accept: HTTP 403, no cloud connection.
            return
        model = ws.query_params.get("model", cfg.realtime_models[0])
        if model not in cfg.realtime_models or set(ws.query_params) - {"model"}:
            await ws.close(code=1008)
            return
        if not admission.acquire("ws", device):
            await ws.close(code=1013)
            return
        tasks = []
        code, reason = 1000, "Session finished"
        try:
            await ws.accept()
            async with asyncio.timeout(cfg.session_seconds):
                async with ws_connector(
                    cfg.realtime_url + "?" + urlencode({"model": model}),
                    additional_headers={"Authorization": "Bearer " + cfg.cloud_key},
                    proxy=None, compression=None, open_timeout=cfg.connect_seconds,
                    close_timeout=3, ping_interval=20, ping_timeout=20,
                    max_size=cfg.max_frame, max_queue=4, write_limit=32768,
                ) as upstream:
                    async def to_cloud():
                        while True:
                            message = await ws.receive()
                            if message["type"] == "websocket.disconnect":
                                return
                            value = message.get("text") if message.get("text") is not None else message.get("bytes")
                            if value is None:
                                continue
                            if len(value.encode() if isinstance(value, str) else value) > cfg.max_frame:
                                raise ValueError("frame limit")
                            await upstream.send(value)

                    async def to_device():
                        async for value in upstream:
                            if len(value.encode() if isinstance(value, str) else value) > cfg.max_frame:
                                raise ValueError("frame limit")
                            if isinstance(value, str):
                                await ws.send_text(value)
                            else:
                                await ws.send_bytes(value)

                    tasks = [asyncio.create_task(to_cloud()), asyncio.create_task(to_device())]
                    try:
                        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                        for task in done:
                            task.result()
                    finally:
                        with anyio.CancelScope(shield=True):
                            for task in tasks:
                                task.cancel()
                            await asyncio.gather(*tasks, return_exceptions=True)
                        tasks = []
        except TimeoutError:
            code, reason = 1001, "Session time limit reached"
        except ValueError:
            code, reason = 1009, "Message too large"
        except (WebSocketDisconnect, ConnectionClosed):
            code, reason = 1011, "Connection ended"
        except Exception as exc:
            # Never log exception text: upstream libraries may include URLs/headers.
            LOG.warning("Realtime upstream failure: %s", type(exc).__name__)
            code, reason = 1011, "Cloud connection failed"
        finally:
            admission.release("ws", device)
            with anyio.CancelScope(shield=True):
                try:
                    await ws.close(code=code, reason=reason)
                except (RuntimeError, OSError):
                    pass

    app = Starlette(routes=[Route("/healthz", health), Route("/v1/models", models),
                            Route("/v1/chat/completions", chat, methods=["POST"]),
                            WebSocketRoute("/v1/realtime", realtime),
                            WebSocketRoute("/api-ws/v1/realtime", realtime)], lifespan=lifespan)
    app.state.admission = admission
    return app
