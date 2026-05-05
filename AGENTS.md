# codex-proxy

OpenAI Responses API 代理：将 Codex CLI 请求翻译为 Z.AI / DeepSeek / Xiaomi Chat Completions API，再将 SSE 响应转回 Responses API 事件流。

## 规则

- 不要自动 git commit 或 git push，除非我明确要求
- 测试用 unittest.mock，不发真实 API 调用
- 无框架，原生 http.server，所有逻辑手写

## 命令

```bash
uv sync                              # 安装依赖
uv run pytest tests/ -v              # 测试
uv run ruff check src/ tests/        # lint
uv run mypy src/                     # 类型检查
uv run codex-proxy                   # 启动 (默认 0.0.0.0:8765)
```

## 请求流

```
CLI -> POST /{provider}/v1/responses
  -> server.py:       路由 + validator 校验原始字段
  -> normalizer.py:   Responses input -> Chat messages
  -> provider:        转发到后端 Chat Completions API
  -> base_stream.py:  后端 SSE -> Responses API 事件流
  -> CLI
```

## 文件速查

| 文件 | 一句话 |
|---|---|
| `server.py` | HTTP 路由、请求分发、日志、/config 认证 |
| `normalizer.py` | input -> messages（含多类型 tool call/output 转换） |
| `validator.py` | 校验原始请求（在 normalize 之前） |
| `config.py` | 三层配置 env > file > defaults，持久化到 ~/.config/codex-proxy/ |
| `providers/base.py` | Provider ABC，同步响应映射，共享 `convert_shell_call()` |
| `providers/base_stream.py` | SSE 流处理，所有 provider 共用 `BaseStreamHandler` |
| `providers/{zai,deepseek,xiaomi}.py` | 各 provider payload 转换 + API 请求 |

## 陷阱

- **validator 在 normalize 之前执行**：原始数据用 `input` 不用 `messages`，messages 校验被跳过是设计如此
- **stream 异常不能冒泡到 do_POST**：headers 已发送后再调 send_error 会崩溃，异常在 `_handle_stream_response` 内部捕获
- **stream 出错发 `response.incomplete`**：不是 `response.completed`，Codex CLI 依赖此状态判断
- **shell call 必须转换**：name 为 shell/container.exec/shell_command 的 function_call 要转为 local_shell_call（Codex CLI 协议），用 `convert_shell_call()`
- **SSE 事件顺序**：response.created -> output_item.added -> [text.delta...] -> output_text.done -> output_item.done -> response.completed
- **配置优先级**：env > config.json > defaults；config_token 为空则不限制 /config 访问
- **debug_mode 默认 false**：生产环境不要开，会记录完整请求体含 API key
