import logging
from typing import Dict, Any
from .base import BaseProvider
from ..config import config

logger = logging.getLogger(__name__)


class DeepSeekProvider(BaseProvider):
    """Provider for DeepSeek models via OpenAI-compatible API."""

    def __init__(self):
        super().__init__(provider_name="DeepSeek", id_prefix="ds_")

    def _get_api_key(self) -> str:
        return config.deepseek_api_key

    def _get_compaction_model(self) -> str:
        return config.deepseek_compaction_model

    def _endpoint(self) -> str:
        url = config.deepseek_url.rstrip("/")
        if not url.endswith("/chat/completions"):
            if not url.endswith("/v1"):
                url += "/v1"
            url += "/chat/completions"
        return url

    def handle_request(self, data: Dict[str, Any], handler: Any) -> None:
        payload = self._prepare_payload(data)
        self._execute_request(payload, data, handler)

    def _prepare_payload(self, data: Dict[str, Any]) -> Dict[str, Any]:
        payload = {
            "model": data.get("model"),
            "messages": data.get("messages", []),
            "stream": data.get("stream", False),
        }
        if "tools" in data:
            payload["tools"] = [
                t for t in data["tools"] if t.get("type") == "function"
            ]
            if not payload["tools"]:
                del payload["tools"]
        for key in ("tool_choice", "temperature", "top_p", "max_tokens"):
            if key in data:
                payload[key] = data[key]
        return payload

    def _transform_messages(self, payload: Dict[str, Any]) -> None:
        for m in payload.get("messages", []):
            if m.get("role") == "developer":
                m["role"] = "system"

    def _execute_request(
        self, payload: Dict[str, Any], original_data: Dict[str, Any], handler: Any
    ) -> None:
        self._transform_messages(payload)

        headers = self._build_headers(original_data)
        if config.deepseek_api_key:
            headers["Authorization"] = f"Bearer {config.deepseek_api_key}"

        stream = payload.get("stream", False)

        try:
            with self.session.post(
                self._endpoint(),
                json=payload,
                headers=headers,
                stream=stream,
                timeout=(config.request_timeout_connect, config.request_timeout_read),
            ) as resp:
                logger.info("DeepSeek response status: %s", resp.status_code)
                if resp.status_code >= 400:
                    logger.error(
                        "DeepSeek error response: %s", resp.text[:500]
                    )
                if stream:
                    self._handle_stream_response(resp, payload, handler)
                else:
                    self._handle_sync_response(resp, original_data, handler)
        except Exception as e:
            logger.error(f"DeepSeek request failed: {e}")
            raise
