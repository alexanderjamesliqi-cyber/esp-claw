# ESP-Claw 服务器转发

设备通过 HTTPS / WSS 连接本服务，由服务器使用千问 API Key 连接云端。支持文字生成、SSE 流式输出和实时语音双向 WebSocket。云端 Key 只存在于服务器环境变量；设备持有单独的访问令牌。

本服务不保存音频、对话或生成的程序，不执行生成代码。语音消息、打断事件和工具调用原样转发，程序执行和硬件操作继续由设备负责。

## 部署（Docker Compose）

需要一台安装 Docker Compose 的 Linux 服务器、解析到该服务器的域名，以及开放的 TCP 80/443 端口。Caddy 自动申请 HTTPS 证书；8000 端口仅在容器网络内开放。

```sh
cd server/espclaw-relay
cp .env.example .env
chmod 600 .env
# 编辑 .env，填写以下配置后启动
docker compose up -d --build
docker compose ps
```

`.env` 中必须填写：

| 配置 | 内容 |
| --- | --- |
| `RELAY_DOMAIN` | 服务器域名，例如 `relay.example.com` |
| `CLOUD_API_KEY` | 对应地域和业务空间的千问 Key，仅放服务器 |
| `CLOUD_REALTIME_URL` | 百炼空间的完整 WSS 地址，不带 `?model=` |
| `DEVICE_TOKENS_JSON` | 设备标识到随机令牌的 JSON 映射 |
| `TEXT_MODELS` | 允许的文字模型，逗号分隔 |
| `REALTIME_MODELS` | 允许的实时语音模型，逗号分隔 |

生成一个设备令牌：

```sh
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
```

将输出放入 `.env`，格式为 `DEVICE_TOKENS_JSON='{"board001":"生成的令牌"}'`。每台设备使用不同令牌，至少 32 字符，不能使用云端 Key。模板中的空配置会拒绝启动。不要提交 `.env`，也不要将它打入固件或发布包。

撤销某台设备：从映射中删除对应设备，执行 `docker compose up -d --force-recreate relay`。更换云端 Key 同样修改 `.env` 并重建 relay 容器，设备令牌不需要改变。重建会断开当前会话。

检查：

```sh
curl https://relay.example.com/healthz
# 预期 {"status":"ok"}；只代表转发进程存活，不代表云端账户额度有效
```

不要开启包含 Authorization、请求正文或音频的代理调试日志。默认不记录访问日志，错误只返回简短分类，不回传云端原始错误内容。不要把 `docker compose config`（会展开环境变量）的输出上传到公开工单。

## 设备接口

所有模型请求带 `Authorization: Bearer <设备令牌>`。服务器会替换为云端 Key，不转发设备提供的其他请求头。设备不能指定任意上游地址。

| 用途 | 地址 |
| --- | --- |
| OpenAI 兼容 Base URL | `https://你的域名/v1` |
| 文字/程序生成 | `POST /v1/chat/completions` |
| 模型列表 | `GET /v1/models` |
| 实时语音 | `wss://你的域名/v1/realtime?model=qwen3.5-omni-flash-realtime` |
| 兼容路径 | `wss://你的域名/api-ws/v1/realtime?model=...` |

文字请求示例正文：

```json
{"model":"qwen-plus","messages":[{"role":"user","content":"你好"}],"stream":true}
```

设备继续发送原有的 `session.update`、`input_audio_buffer.append`、`response.cancel` 和工具调用结果。模型名称必须同时被服务器允许、被当前百炼空间开通。服务器透明转发，不自动重试语音事件，避免重复对话。设备遇到断线需停止播放、清理当前会话，并退避重连；不要在循环中立即不断重试。

**当前集成状态：** 后端已实现并通过本地模拟云端测试。本次没有刷机，也没有改变设备当前直连云端的设置。当前固件的实时语音地址校验仅允许阿里云域名；部署后还需要在固件中适配服务器域名、TLS 信任及独立设备令牌，删除设备上的云端 Key，再做真机端到端验证。只修改实时语音 URL 不能完成当前固件的切换。

## 资源和并发

默认最多 16 个 HTTP 请求、16 个实时会话；每台设备最多 2 个 HTTP 请求和 1 个实时会话，每分钟最多启动 60 次请求/会话。超限立即拒绝，不堆积等待队列。WebSocket 握手拒绝表现为 HTTP 403；已接通后以简短关闭原因结束。

HTTP 请求最大 1 MiB，响应累计最大 16 MiB，总时限 120 秒；请求体读取最多 15 秒。实时语音单消息最大 256 KiB，接收队列最多 4 条，会话最长 900 秒。发送等待下游，形成背压。断开流式连接会关闭上游并释放会话；尚未返回响应头的 HTTP 请求最长受总超时限制。单条大响应、过慢连接或超时会被中止。

环境模板可调整并发、频率和超时时间。Compose 将 relay 内存限制为 512 MiB、Caddy 为 128 MiB；这些是保护上限，不是生产负载容量证明，增加并发前需实测内存和带宽。服务采用单 worker；限流状态保存在进程内，重启会重置。扩展为多进程/多服务器前需实现共享配额，不能直接增加 worker 后仍按全局限额理解。

没有账户管理、用量计费或管理后台；当前适合受控设备列表。设备令牌可独立撤销，但不构成按用户计费系统。

## 本地运行与验证

Python 3.12：

```sh
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests -q
# 准备好 .env 后，可供本机反向代理转发
.venv/bin/uvicorn relay:create_app --factory --env-file .env --host 127.0.0.1 --port 8000 --workers 1 --no-access-log --ws-max-size 262144 --ws-max-queue 4 --limit-concurrency 64
```

18 项测试覆盖设备鉴权、云端凭据替换、模型白名单、请求/响应上限、云端错误隐藏、超时、限流、SSE 清理，以及 WebSocket 文本/二进制转发、打断消息、断线重连和连接配额释放。网络集成测试使用真实本地 TCP 与模拟云端，不使用真实 Key，不产生云端费用。

本地已验证 Python 服务；Docker/Caddy 的公网证书签发和设备到真实千问的完整链路需在目标服务器部署后验证。

接口参考：[阿里云实时语音 WebSocket 文档](https://help.aliyun.com/en/model-studio/realtime-websocket-overview)。

## Spark 生产部署（2026-09-30）

部署站点 `https://spark.mpython.cn`，HTTP 入口 `/v1/chat/completions`，实时语音 `/api-ws/v1/realtime`。
生产必须设置 `DEVICE_REGISTRY_URL=http://127.0.0.1:3000/internal/device-keys`，不配置静态设备 token。
`POST /v1/auth/challenge` 使用 `deviceId`、`publicKey`、离线 `certificate` 与请求 SHA256 获取单次挑战。
HTTP Bearer 为 `base64(JSON({deviceId,challengeId,signature}))`；signature 是 P-256/SHA256 DER 签名的 base64。
HTTP 同时提交 `X-Spark-Request-Hash`（原始请求体字节的 SHA256）；WebSocket 摘要是 UTF-8 `realtime:<model>` 的 SHA256。
`/v1/models` 摘要为 UTF-8 `models` 的 SHA256。每个证明只能使用一次，30 秒过期。

GitHub `.github/workflows/spark-relay.yml` 在 `labplus-claw` 的相关路径推送后先测试再部署。Secrets 仅含受限部署 SSH 私钥与固定 known_hosts；千问 API Key 在 `/etc/spark-relay/runtime.env`（root 0600）。
健康检查失败自动恢复上一发布目录。只有 Nginx 80/443 对外，后端绑定 127.0.0.1:8000。
本次 key 的文字调用与 `wss://dashscope.aliyuncs.com/api-ws/v1/realtime` 的 `qwen3.5-omni-flash-realtime` 建连均已验证；历史代码中的 workspace 域名对此 key 返回 403，生产已改用经验证的公共域名。

出厂流程和硬件安全未验证边界见 `integration/labplus/FACTORY_IDENTITY.md`。服务器只保存厂商公钥和设备黑名单，无需逐台登记。实时语音每 5 秒检查黑名单，拉黑或检查失败后关闭连接。
