import copy
import logging
from typing import Any

from ..config import config
from .base import BaseProvider

logger = logging.getLogger(__name__)


class ZAIProvider(BaseProvider):
    """Provider for Z.AI GLM models."""

    def __init__(self):
        super().__init__(provider_name="ZAI", id_prefix="zai_")

    @property
    def _use_passthrough_auth(self) -> bool:
        return True

    def _get_api_key(self) -> str:
        return config.zai_api_key

    def _get_compaction_model(self) -> str:
        return config.zai_compaction_model

    def _endpoint(self) -> str:
        url = config.zai_url.rstrip("/")
        if not url.endswith("/chat/completions"):
            url += "/chat/completions"
        return url

    def handle_request(self, data: dict[str, Any], handler: Any) -> None:
        payload = self._prepare_payload(data)
        self._transform_payload(payload)
        self._execute_request(payload, data, handler)

    def _prepare_payload(self, data: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "model": data.get("model", ""),
            "messages": data.get("messages", []),
            "stream": data.get("stream", False),
        }
        if "tools" in data:
            payload["tools"] = data["tools"]
        if "tool_choice" in data:
            payload["tool_choice"] = data["tool_choice"]
        if "temperature" in data:
            payload["temperature"] = data["temperature"]
        if "top_p" in data:
            payload["top_p"] = data["top_p"]
        if "max_tokens" in data:
            payload["max_tokens"] = data["max_tokens"]
        return payload

    def _transform_payload(self, payload: dict[str, Any]) -> None:
        for m in payload.get("messages", []):
            if m.get("role") == "developer":
                m["role"] = "system"

        if payload.get("tools"):
            transformed_tools = []
            for tool in payload["tools"]:
                ttype = tool.get("type")
                if ttype == "function":
                    t = copy.deepcopy(tool)
                    if "strict" in t:
                        del t["strict"]
                    transformed_tools.append(t)
                elif ttype == "web_search":
                    transformed_tools.append(
                        {
                            "type": "web_search",
                            "web_search": {
                                "enable": True,
                                "search_engine": "search_pro_jina",
                            },
                        }
                    )
            payload["tools"] = transformed_tools

    def _execute_request(
        self, payload: dict[str, Any], original_data: dict[str, Any], handler: Any
    ) -> None:
        headers = self._build_headers(original_data)
        auth_header = handler.headers.get("Authorization")
        if config.zai_api_key:
            auth_header = f"Bearer {config.zai_api_key}"
        if auth_header:
            headers["Authorization"] = auth_header

        stream = payload.get("stream", False)

        try:
            with self._post_with_retry(
                self._endpoint(),
                json=payload,
                headers=headers,
                stream=stream,
                timeout=(config.request_timeout_connect, config.request_timeout_read),
            ) as resp:
                logger.info("Z.AI response status: %s", resp.status_code)
                if stream:
                    self._handle_stream_response(resp, payload, handler, original_data)
                else:
                    self._handle_sync_response(resp, original_data, handler)
        except Exception as e:
            logger.error(f"ZAI Request failed: {e}")
            raise
