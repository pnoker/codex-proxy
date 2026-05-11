# codex-proxy

[![CI](https://github.com/cornellsh/codex-proxy/workflows/CI/badge.svg)](https://github.com/cornellsh/codex-proxy/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)

**An OpenAI Responses API proxy for Z.AI, DeepSeek, and Xiaomi providers.**

Translates OpenAI's Responses API to Z.AI (GLM), DeepSeek, and Xiaomi chat completions APIs. Handles wire format differences, role mapping, and SSE stream formatting so [Codex CLI](https://github.com/openai/codex) can use these providers.

## Features

- **Responses API** — Full lifecycle with SSE events (`response.created` → `output_text.delta` / `reasoning_summary_text.delta` → `response.completed`)
- **Multi-Provider** — Z.AI (GLM), DeepSeek, and Xiaomi support
- **Context Compaction** — All three providers support the `/compact` endpoint
- **Tool Support** — Function calling mapped to Codex tool-call types (`local_shell_call`, `function_call`, `web_search`)
- **Model Injection** — Inject custom model metadata into Codex CLI's cache for accurate context window / feature detection
- **Container Ready** — Production container with podman-compose / docker-compose

## Quick Start

### 1. Clone

```bash
git clone https://github.com/cornellsh/codex-proxy.git
cd codex-proxy
```

### 2. Configure

Copy `.env.example` to `.env` and fill in your API keys:

```bash
cp .env.example .env
```

```dotenv
# DeepSeek
CODEX_PROXY_DEEPSEEK_API_KEY=your-deepseek-api-key

# Z.AI (GLM)
CODEX_PROXY_ZAI_API_KEY=your-zai-api-key

# Xiaomi
CODEX_PROXY_XIAOMI_API_KEY=your-xiaomi-api-key
```

### 3. Start

```bash
# Podman (recommended)
podman compose -f config/docker-compose.yml down && podman compose -f config/docker-compose.yml up -d --build

# Or Docker
docker compose -f config/docker-compose.yml down && docker compose -f config/docker-compose.yml up -d --build

# Or run directly
uv run codex-proxy
```

### 4. Inject Model Metadata

Codex CLI only ships metadata for official OpenAI models. Inject custom model metadata so Codex can correctly detect context window size and feature support:

```bash
python scripts/inject_models.py              # inject
python scripts/inject_models.py --dry-run    # preview only
python scripts/inject_models.py --list       # show current cache
```

### 5. Configure Codex CLI

Edit `~/.codex/config.toml` to point Codex at the proxy:

```toml
model_provider = "codex-proxy"
model = "deepseek-v4-pro"
model_reasoning_effort = "xhigh"
disable_response_storage = true

[model_providers.codex-proxy]
name = "codex-proxy"
base_url = "http://localhost:8765/deepseek/v1"
wire_api = "responses"
requires_openai_auth = true
```

Replace `base_url` path prefix for other providers:

| Provider | Base URL |
|----------|----------|
| DeepSeek | `http://localhost:8765/deepseek/v1` |
| Z.AI | `http://localhost:8765/zai/v1` |
| Xiaomi | `http://localhost:8765/xiaomi/v1` |

## Development

Lint, format, and type-check are configured in [pyproject.toml](pyproject.toml) under `[tool.ruff]` and `[tool.mypy]`. All tooling runs through `uv`:

```bash
uv run ruff check .            # Lint
uv run ruff check . --fix      # Lint and auto-fix
uv run ruff format .           # Format (Black-compatible)
uv run mypy src                # Static type check
uv run pytest -q               # Run tests
```

Ruff replaces Black, isort, Flake8, pyupgrade, and several other tools with one Rust-based binary. Enabled rule families: `E/W/F/I/B/UP/SIM/RUF`. Line length is 100, target is `py312`.

## Documentation

- [CONTRIBUTING.md](CONTRIBUTING.md) — Development guide and contribution process

## License

MIT License — see [LICENSE](LICENSE)
