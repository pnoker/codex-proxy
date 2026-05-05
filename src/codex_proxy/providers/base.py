import time
import logging
import requests
from abc import ABC, abstractmethod
from http.server import BaseHTTPRequestHandler
from typing import Any, Dict

from .base_stream import BaseStreamHandler, convert_shell_call
from ..utils import create_session, json_dumps
from ..config import config

logger = logging.getLogger(__name__)

# Codex context headers to forward upstream
_FORWARD_HEADERS = (
    "session_id",
    "x-openai-subagent",
    "x-codex-turn-state",
    "x-codex-personality",
)


_MAX_429_RETRIES = 5
_INITIAL_BACKOFF = 1.0
_MAX_BACKOFF = 30.0


class BaseProvider(ABC):
    """Abstract base class for AI model providers."""

    def __init__(self, *, provider_name: str, id_prefix: str):
        self.provider_name = provider_name
        self.id_prefix = id_prefix
        self.session = create_session()

    @abstractmethod
    def handle_request(
        self, data: Dict[str, Any], handler: BaseHTTPRequestHandler
    ) -> None:
        pass

    @abstractmethod
    def _endpoint(self) -> str:
        pass

    @abstractmethod
    def _get_api_key(self) -> str:
        pass

    @abstractmethod
    def _get_compaction_model(self) -> str:
        pass

    @property
    def _use_passthrough_auth(self) -> bool:
        return False

    @staticmethod
    def _build_headers(data: Dict[str, Any]) -> Dict[str, str]:
        headers: Dict[str, str] = {}
        ctx = data.get("_headers", {})
        for key in _FORWARD_HEADERS:
            val = ctx.get(key)
            if val:
                headers[key] = val
        return headers

    # ------------------------------------------------------------------
    # HTTP request with 429 retry
    # ------------------------------------------------------------------

    def _post_with_retry(self, url: str, **kwargs) -> requests.Response:
        backoff = _INITIAL_BACKOFF
        for attempt in range(_MAX_429_RETRIES + 1):
            resp = self.session.post(url, **kwargs)
            if resp.status_code != 429:
                return resp

            if attempt == _MAX_429_RETRIES:
                logger.warning(
                    "[%s] 429 retry exhausted after %d attempts",
                    self.provider_name, _MAX_429_RETRIES,
                )
                return resp

            retry_after = resp.headers.get("Retry-After")
            if retry_after:
                try:
                    wait = min(float(retry_after), _MAX_BACKOFF)
                except ValueError:
                    wait = backoff
            else:
                wait = backoff

            logger.warning(
                "[%s] 429 rate limited, retry %d/%d after %.1fs",
                self.provider_name, attempt + 1, _MAX_429_RETRIES, wait,
            )
            time.sleep(wait)
            backoff = min(backoff * 2, _MAX_BACKOFF)

        return resp  # unreachable but satisfies type checker

    # ------------------------------------------------------------------
    # Shared response handlers
    # ------------------------------------------------------------------

    def _handle_stream_response(
        self, resp: requests.Response, payload: Dict[str, Any], handler: Any
    ) -> None:
        handler.send_response(resp.status_code)
        handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
        handler.send_header("Connection", "keep-alive")
        handler.end_headers()

        created_ts = int(time.time())
        stream_handler = BaseStreamHandler(
            handler, payload["model"], created_ts, payload,
            provider_name=self.provider_name,
        )
        try:
            stream_handler.process_stream(resp)
        except Exception as e:
            logger.error(
                f"Stream error after headers sent for {self.provider_name}: {e}",
                exc_info=True,
            )

    def _handle_sync_response(
        self, resp: requests.Response, original_data: Dict[str, Any], handler: Any
    ) -> None:
        handler.send_response(resp.status_code)
        handler.send_header("Content-Type", "application/json")
        handler.end_headers()

        if original_data.get("_is_responses_api") and resp.status_code == 200:
            try:
                self._write_mapped_response(resp, handler)
                return
            except Exception as e:
                logger.warning(f"Failed to map {self.provider_name} response: {e}")

        handler.wfile.write(resp.content)

    def _write_mapped_response(self, resp: requests.Response, handler: Any) -> None:
        r_data = resp.json()
        choice = r_data["choices"][0]
        message = choice["message"]
        usage = r_data.get("usage", {})

        output_items = []
        if "tool_calls" in message:
            for tc in message["tool_calls"]:
                item = {
                    "id": tc.get("id"),
                    "type": "function_call",
                    "status": "completed",
                    "name": tc["function"]["name"],
                    "arguments": tc["function"]["arguments"],
                    "call_id": tc.get("id"),
                }
                convert_shell_call(item)
                output_items.append(item)

        if message.get("content"):
            output_items.append(
                {
                    "id": f"msg_{int(time.time() * 1000)}",
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": message["content"]}],
                }
            )

        resp_obj = {
            "id": f"{self.id_prefix}{r_data.get('id')}",
            "object": "response",
            "created": r_data.get("created"),
            "model": r_data.get("model"),
            "status": "completed",
            "usage": {
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
            },
            "output": output_items,
        }
        handler.wfile.write(json_dumps(resp_obj))
        logger.info(
            "[%s] << 200 items=%d tokens=%d/%d/%d",
            self.provider_name, len(output_items),
            resp_obj["usage"]["prompt_tokens"],
            resp_obj["usage"]["completion_tokens"],
            resp_obj["usage"]["total_tokens"],
        )

    # ------------------------------------------------------------------
    # Shared compaction handler
    # ------------------------------------------------------------------

    def handle_compact(
        self, data: Dict[str, Any], handler: BaseHTTPRequestHandler
    ) -> None:
        compaction_model = config.get_model(data.get("model", self._get_compaction_model()))

        messages = data.get("input", [])
        if isinstance(messages, str):
            messages = [{"role": "user", "content": messages}]
        else:
            messages = list(messages)
        compaction_prompt = data.get(
            "instructions", "Summarize the conversation history concisely."
        )

        messages.append(
            {
                "role": "user",
                "content": f"Perform context compaction. instructions: {compaction_prompt}",
            }
        )

        payload = {
            "model": compaction_model,
            "messages": messages,
            "stream": False,
            "temperature": config.compaction_temperature,
            "max_tokens": config.compaction_max_tokens,
        }

        headers = self._build_headers(data)
        api_key = self._get_api_key()
        if self._use_passthrough_auth:
            auth_header = handler.headers.get("Authorization")
            if not auth_header and api_key:
                auth_header = f"Bearer {api_key}"
        else:
            auth_header = f"Bearer {api_key}" if api_key else None
        if auth_header:
            headers["Authorization"] = auth_header

        try:
            with self._post_with_retry(
                self._endpoint(),
                json=payload,
                headers=headers,
                timeout=(config.request_timeout_connect, config.request_timeout_read),
            ) as resp:
                if resp.status_code != 200:
                    logger.error(f"Compaction request failed: {resp.status_code}")
                    handler.send_error(resp.status_code, resp.text)
                    return

                r_data = resp.json()
                choice = r_data.get("choices", [{}])[0]
                final_text = choice.get("message", {}).get("content", "")

                result = {
                    "output": [{"type": "compaction", "encrypted_content": final_text}]
                }

                handler.send_response(200)
                handler.send_header("Content-Type", "application/json")
                handler.end_headers()
                handler.wfile.write(json_dumps(result))

        except Exception as e:
            logger.error(f"Compaction failed: {e}")
            handler.send_error(500, str(e))
