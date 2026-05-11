# codex-proxy

OpenAI Responses API proxy: translates Codex CLI requests into Z.AI / DeepSeek / Xiaomi Chat Completions calls and converts the SSE responses back into Responses API events.

## Rules

- Do not auto `git commit` or `git push` unless I explicitly ask.
- Tests use `unittest.mock`; never make real API calls.
- No frameworks. Plain `http.server`, all logic written by hand.

## Commands

```bash
uv sync                              # install dependencies
uv run pytest -q                     # tests
uv run ruff check .                  # lint
uv run ruff format .                 # format
uv run mypy src                      # type check
uv run codex-proxy                   # start (default 127.0.0.1:8765)
```

## Request Flow

```
CLI -> POST /{provider}/v1/responses
  -> server.py:       routing + validator on raw fields
  -> normalizer.py:   Responses input -> Chat messages
  -> provider:        forward to backend Chat Completions API
  -> base_stream.py:  backend SSE -> Responses API event stream
  -> CLI
```

## File Map

| File | One-liner |
|---|---|
| `server.py` | HTTP routing, request dispatch, logging |
| `normalizer.py` | `input` -> `messages` (covers all tool-call / tool-output variants) |
| `validator.py` | Validate the raw request (runs *before* normalize) |
| `config.py` | Env-only configuration via `CODEX_PROXY_*` variables |
| `providers/base.py` | Provider ABC, sync response mapping, shared `convert_shell_call()` |
| `providers/base_stream.py` | SSE stream handling shared by every provider via `BaseStreamHandler` |
| `providers/{zai,deepseek,xiaomi}.py` | Provider-specific payload transforms and API calls |

## Pitfalls

- **Validator runs before normalize.** Raw payloads use `input`, not `messages`, so the `messages` checks are skipped on purpose at the raw stage.
- **Stream exceptions must not bubble to `do_POST`.** Once headers are flushed, calling `send_error` crashes the handler. Catch inside `_handle_stream_response`.
- **On stream failure emit `response.incomplete`,** not `response.completed` — Codex CLI relies on that state.
- **Shell-call conversion depends on the client.** macOS/Linux Codex CLI registers a `{"type": "local_shell"}` builtin, so `function_call`s named `shell` / `container.exec` / `shell_command` must be rewritten to `local_shell_call`. Windows Codex CLI registers a plain `shell` function with no `local_shell` builtin — converting there triggers `unsupported call: local_shell_command`. `convert_shell_call(item, has_local_shell=...)` decides based on the request's tool list.
- **SSE event order:** `response.created` → `output_item.added` → `[text.delta…]` → `output_text.done` → `output_item.done` → `response.completed`.
- **Configuration is env-only:** `CODEX_PROXY_*` variables. There is no config file, no `/config` endpoint, no auth token.
- **`debug_mode` is `false` by default.** Do not enable in production — it logs full request bodies including API keys.
