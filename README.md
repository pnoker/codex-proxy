# codex-proxy

[![CI](https://github.com/cornellsh/codex-proxy/workflows/CI/badge.svg)](https://github.com/cornellsh/codex-proxy/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)

**An OpenAI Responses API proxy for Z.AI, DeepSeek, and Xiaomi providers.**

Translates OpenAI's Responses API to Z.AI (GLM), DeepSeek, and Xiaomi chat completions APIs. Handles wire format differences, role mapping, and SSE stream formatting so Codex CLI can use these providers.

## Features

- **Responses API** — Full lifecycle with SSE events (`response.created` → `output_item.added` → `output_text.delta` / `reasoning_summary_text.delta` → `output_item.done` → `response.completed`)
- **Multi-Provider** — Z.AI (GLM), DeepSeek, and Xiaomi support
- **Context Compaction** — All three providers support the `/compact` endpoint
- **Tool Support** — Function calling mapped to Codex tool-call types (`local_shell_call`, `function_call`, `web_search`)
- **Config UI** — Built-in web UI at `/ui` for live configuration editing
- **Docker Ready** — Production container with hot-reload via docker-compose / podman-compose

## Quick Start

```bash
# Clone and start
git clone https://github.com/cornellsh/codex-proxy.git
cd codex-proxy

# Run directly (Python 3.14+ required)
python -m codex_proxy

# Or via Docker
docker compose -f config/docker-compose.yml up -d
```

## Configuration

Configuration lives at `~/.config/codex-proxy/config.json`. Environment variables override all settings. You can also edit config live via the web UI at `http://localhost:8765/ui`.

### Server Settings

| Env Var | Config Key | Description | Default |
|----------|-------------|-------------|----------|
| `CODEX_PROXY_PORT` | `port` | Port to listen on | `8765` |
| `CODEX_PROXY_LOG_LEVEL` | `log_level` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) | `DEBUG` |
| `CODEX_PROXY_DEBUG` | `debug_mode` | Enable debug mode (logs raw requests) | `true` |

### Provider Authentication

| Env Var | Config Key | Description | Default |
|----------|-------------|-------------|----------|
| `CODEX_PROXY_ZAI_API_KEY` | `zai_api_key` | Z.AI API key | — |
| `CODEX_PROXY_DEEPSEEK_API_KEY` | `deepseek_api_key` | DeepSeek API key | — |
| `CODEX_PROXY_XIAOMI_API_KEY` | `xiaomi_api_key` | Xiaomi API key | — |

### API Endpoints

| Env Var | Config Key | Description | Default |
|----------|-------------|-------------|----------|
| `CODEX_PROXY_ZAI_URL` | `zai_url` | Z.AI API base URL | `https://api.z.ai/api/coding/paas/v4` |
| `CODEX_PROXY_DEEPSEEK_URL` | `deepseek_url` | DeepSeek API base URL | `https://api.deepseek.com` |
| `CODEX_PROXY_XIAOMI_URL` | `xiaomi_url` | Xiaomi API base URL | `https://api.llm.mioffice.cn/v1` |

### Timeout Settings

| Config Key | Description | Default |
|------------|-------------|----------|
| `request_timeout_connect` | Connection timeout (seconds) | `10` |
| `request_timeout_read` | Read timeout (seconds) | `600` |
| `compaction_temperature` | Temperature for compaction requests | `0.1` |

### Example Config

```json
{
  "port": 8765,
  "log_level": "INFO",
  "debug_mode": false,
  "zai_api_key": "your-z-ai-key",
  "zai_url": "https://api.z.ai/api/coding/paas/v4",
  "deepseek_api_key": "your-deepseek-key",
  "deepseek_url": "https://api.deepseek.com",
  "xiaomi_api_key": "your-xiaomi-key",
  "xiaomi_url": "https://api.llm.mioffice.cn/v1",
  "request_timeout_connect": 10,
  "request_timeout_read": 600,
  "compaction_temperature": 0.1
}
```

## API Usage

The Codex CLI routes requests to this proxy. Each provider has its own path prefix:

| Provider | Responses endpoint | Compact endpoint |
|----------|--------------------|------------------|
| Z.AI | `/zai/v1/responses` | `/zai/v1/responses/compact` |
| DeepSeek | `/deepseek/v1/responses` | `/deepseek/v1/responses/compact` |
| Xiaomi | `/xiaomi/v1/responses` | `/xiaomi/v1/responses/compact` |

Context headers (`session_id`, `x-openai-subagent`, `x-codex-turn-state`, `x-codex-personality`) are forwarded from incoming requests to upstream providers.

## Documentation

- [CONTRIBUTING.md](CONTRIBUTING.md) — Development guide and contribution process

## License

MIT License — see [LICENSE](LICENSE)
