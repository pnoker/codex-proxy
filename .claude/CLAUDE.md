# codex-proxy

OpenAI Responses API 代理服务，将 Codex CLI 的请求翻译成 Z.AI / DeepSeek / Xiaomi 的 API 格式，再将响应转回 Codex 兼容的 SSE 事件流。

## 技术栈

- Python 3.14+, hatchling 构建, uv 管理依赖
- 多线程 HTTP 服务器 (ThreadingMixIn + HTTPServer), 无框架依赖
- orjson 加速序列化 (fallback 到 json)
- requests + urllib3 做 HTTP 客户端
- python-dotenv 自动加载 .env

## 常用命令

```bash
# 安装依赖
uv sync

# 运行测试
uv run pytest tests/ -v

# 本地启动服务 (默认 0.0.0.0:8765)
uv run codex-proxy

# Docker 方式
./scripts/control.sh start|stop|logs|test
./scripts/control.sh run -- "prompt"

# Lint
uv run ruff check src/ tests/
uv run mypy src/
```

## 项目结构

```
src/codex_proxy/
  main.py              # 入口: setup_logging + run_server
  server.py            # HTTP 路由, 路径提取 provider, 请求分发
  config.py            # Config dataclass, 三层优先级: env > file > defaults
  normalizer.py        # Responses API -> OpenAI chat 格式转换
  validator.py         # 请求参数校验
  ui.py                # 内嵌配置管理 UI (单页 HTML)
  utils.py             # JSON 序列化, 日志, HTTP session
  exceptions.py        # 异常层级
  providers/
    base.py            # ABC: handle_request / handle_compact
    zai.py             # ZAIProvider: Z.AI API, payload 转换
    zai_stream.py      # Z.AI SSE -> Codex Responses API 事件
    deepseek.py        # DeepSeekProvider: DeepSeek API
    deepseek_stream.py # DeepSeek SSE -> Codex Responses API 事件
    xiaomi.py          # XiaomiProvider: Xiaomi API
    xiaomi_stream.py   # Xiaomi SSE -> Codex Responses API 事件
tests/
  conftest.py          # sys.path
  test_server.py       # 路由, 校验, compaction, 错误处理
  test_config.py       # 配置默认值, 校验, 环境变量覆盖
  test_validator.py    # 请求校验各字段
  test_normalizer.py   # 标准化逻辑
  test_providers.py    # Provider 注册与实例化
```

## 核心请求流

```
Codex CLI -> POST /{provider}/v1/responses
  -> 路径提取 provider 名称
  -> RequestValidator.validate_request()
  -> RequestNormalizer.normalize()          # Responses API -> chat 格式
  -> Provider.handle_request()              # 转发到后端
  -> StreamHandler.stream_responses_loop()  # 后端 SSE -> Codex 事件
  -> Codex CLI 接收
```

## Provider 路由

URL 路径前缀决定 provider（不再依赖模型名前缀）：

| 路径 | Provider | 后端 API |
|---|---|---|
| `/zai/v1/responses` | ZAIProvider | api.z.ai (Chat Completions) |
| `/deepseek/v1/responses` | DeepSeekProvider | api.deepseek.com (Chat Completions) |
| `/xiaomi/v1/responses` | XiaomiProvider | api.llm.mioffice.cn (Chat Completions) |

Codex CLI 通过 `model_providers` 配置各自的 `base_url` 指向对应路径。

## 环境变量

每个 provider 的 Base URL 和 API Key 均通过 `.env` 配置：

- `CODEX_PROXY_{PROVIDER}_URL` — 后端 API 地址
- `CODEX_PROXY_{PROVIDER}_API_KEY` — 认证密钥
- `CODEX_PROXY_PORT` — 服务端口 (默认 8765)
- `CODEX_PROXY_LOG_LEVEL` — 日志级别 (默认 DEBUG)

## 关键设计

- **路由隔离**: 每个 provider 独立的 URL 命名空间，不再跨 provider 路由
- **Compaction**: 每个 provider 自己的 `/compact` 端点使用自己的模型
- **Reasoning 处理**: `reasoning_content` 作为独立 reasoning 输出项，与 content 分离
- **Tools 过滤**: 只转发 `type: "function"` 的 tools，过滤 `namespace` 等非标准类型
- **配置持久化**: POST /config 写入 ~/.config/codex-proxy/config.json

## 编码规范

- 无框架, 原生 http.server, 所有逻辑手写
- 测试用 unittest.mock, 不发真实 API 调用
- 配置优先级: 环境变量 > config.json > 内置默认值
- SSE 流按 Codex Responses API 协议格式输出事件
