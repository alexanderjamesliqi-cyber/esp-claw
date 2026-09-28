# Secure WebSocket client

Use `require('websocket')` for direct device-to-cloud sessions. Create a client
with `websocket.new({url='wss://…', headers='Authorization: Bearer …\r\n'})`.
Never log credentials. TLS certificates are verified against the IDF bundle.

The connection starts asynchronously. Use `client:receive(timeout_ms)` to await
application messages (0–10000 ms); nil means no message yet. `client:send(text)`
queues UTF-8 text once connected; success means accepted, not delivered. A dedicated
worker performs network writes so a slow peer cannot block the UI. Connection errors and queue overflow raise an
error; close the client and reconnect explicitly with bounded backoff.

`client:close()` detaches immediately; a cleanup worker joins network tasks before
freeing their heap-owned state. GC uses the same path. At most two clients may be
live or closing; retry after a bounded delay when cleanup is pending. The outbound
queue holds at most 32 messages / 512 KiB (plus one in-flight message).

Applications may use `configured_auth=true` with an application-registered credential
provider. The provider validates the endpoint and reads in-memory configuration;
credentials are never returned to Lua or fetched through localhost HTTP.
The queue holds at most 128 messages and 4 MiB total payload, each limited to 256 KiB. WebSocket fragments
are reassembled before delivery. Ping frames are handled by the IDF client.

`websocket.base64_encode(bytes)` and `base64_decode(text)` support realtime PCM
payloads. Each input is limited to 256 KiB.

For full-duplex realtime audio, enable `CONFIG_ESP_WS_CLIENT_SEPARATE_TX_LOCK`; otherwise a receive can hold the same lock needed to send an interruption.
