# codex-proxy

OpenAI Responses API 代理：将 Codex CLI 请求翻译为 Z.AI / DeepSeek / Xiaomi 的 Chat Completions API，再将 SSE 响应转回 Responses API 事件流。

## 行为规则

- 不要自动 git commit 或 git push，除非我明确要求
- 测试用 unittest.mock，不发真实 API 调用
- 无框架，原生 http.server，所有逻辑手写
- 不要在 normalizer.py 之前操作 messages 字段（Responses API 用 input，normalize 后才有 messages）

## 命令

```bash
uv sync                                # 安装依赖
uv run pytest tests/ -v                # 测试
uv run ruff check src/ tests/          # lint
uv run mypy src/                       # 类型检查
uv run codex-proxy                     # 启动 (0.0.0.0:8765)
./scripts/control.sh start|stop|logs   # Docker
```

## 请求流

```
CLI -> POST /{provider}/v1/responses
  -> server.py: 路径提取 provider + validator 校验原始字段
  -> normalizer.py: input (Responses API) -> messages (Chat 格式)
  -> provider.handle_request(): 转发到后端 Chat Completions API
  -> base_stream.py: 后端 SSE -> Responses API 事件流 -> CLI
```

provider 由路径前缀决定（`/zai/`、`/deepseek/`、`/xiaomi/`），每个有独立 `/compact` 端点。

## 文件职责

| 文件 | 职责 |
|---|---|
| `server.py` | HTTP 路由、请求分发、日志、/config 认证 (config_token) |
| `normalizer.py` | Responses API input -> Chat messages，含 tool call/output 多类型转换 |
| `validator.py` | 校验原始请求（在 normalize 之前，不校验 messages） |
| `config.py` | Config dataclass，三层覆盖 env > file > defaults，持久化到 ~/.config/codex-proxy/ |
| `providers/base.py` | Provider ABC，同步响应映射，`convert_shell_call()` 共用入口 |
| `providers/base_stream.py` | SSE 流处理，所有 provider 共用 `BaseStreamHandler` + `convert_shell_call()` |
| `providers/{zai,deepseek,xiaomi}.py` | 各 provider 的 payload 转换 + API 请求 |

## 注意事项

- **validator 在 normalize 之前**：Responses API 原始数据用 `input` 不用 `messages`，所以 messages 校验会被跳过，这是设计如此，不是 bug
- **shell call 转换**：`function_call` 中 name 为 shell/container.exec/shell_command 的必须转换为 `local_shell_call`（Codex CLI 协议），`convert_shell_call()` 是共享实现
- **stream 异常**：headers 发送后不能再调 send_error，异常在 `_handle_stream_response` 内部捕获；出错时发 `response.incomplete` 不是 `response.completed`
- **SSE 事件序列**：`response.created -> output_item.added -> [text.delta...] -> output_text.done -> output_item.done -> response.completed`
- **配置优先级**：环境变量 > config.json > 内置默认值
- **debug_mode 默认 false**：开启后记录完整请求体，生产环境不要开
