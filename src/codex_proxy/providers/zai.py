import time
import logging
import requests
from typing import Dict, Any
from .base import BaseProvider
from ..utils import create_session, json_loads, json_dumps
from ..config import config
from .zai_stream import stream_responses_loop

logger = logging.getLogger(__name__)


class ZAIProvider(BaseProvider):
    """Provider for Z.AI GLM models."""

    def __init__(self):
        self.session = create_session()

    def _endpoint(self) -> str:
        url = config.zai_url.rstrip("/")
        if not url.endswith("/chat/completions"):
            url += "/chat/completions"
        return url

    def handle_request(self, data: Dict[str, Any], handler: Any) -> None:
        payload = self._prepare_payload(data)
        self._transform_payload(payload)
        self._execute_request(payload, data, handler)

    def _prepare_payload(self, data: Dict[str, Any]) -> Dict[str, Any]:
        payload = {
            "model": data.get("model"),
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

    def _transform_payload(self, payload: Dict[str, Any]) -> None:
        for m in payload.get("messages", []):
            if m.get("role") == "developer":
                m["role"] = "system"

        if "tools" in payload and payload["tools"]:
            transformed_tools = []
            for tool in payload["tools"]:
                ttype = tool.get("type")
                if ttype == "function":
                    if "strict" in tool:
                        del tool["strict"]
                    transformed_tools.append(tool)
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
        self, payload: Dict[str, Any], original_data: Dict[str, Any], handler: Any
    ) -> None:
        auth_header = handler.headers.get("Authorization")
        if config.zai_api_key:
            auth_header = f"Bearer {config.zai_api_key}"

        stream = payload.get("stream", False)

        try:
            with self.session.post(
                self._endpoint(),
                json=payload,
                headers={"Authorization": auth_header} if auth_header else {},
                stream=stream,
                timeout=(config.request_timeout_connect, config.request_timeout_read),
            ) as resp:
                logger.info("Z.AI response status: %s", resp.status_code)
                if stream:
                    self._handle_stream_response(resp, payload, handler)
                else:
                    self._handle_sync_response(resp, original_data, handler)
        except Exception as e:
            logger.error(f"ZAI Request failed: {e}")
            raise e

    def _handle_stream_response(
        self, resp: requests.Response, payload: Dict[str, Any], handler: Any
    ) -> None:
        handler.send_response(resp.status_code)
        handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
        handler.send_header("Connection", "keep-alive")
        handler.end_headers()

        created_ts = int(time.time())
        stream_responses_loop(resp, handler, payload["model"], created_ts, payload)

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
                logger.warning(f"Failed to map ZAI response: {e}")

        handler.wfile.write(resp.content)

    def _write_mapped_response(self, resp: requests.Response, handler: Any) -> None:
        z_data = resp.json()
        choice = z_data["choices"][0]
        message = choice["message"]
        usage = z_data.get("usage", {})

        output_items = []
        if "tool_calls" in message:
            for tc in message["tool_calls"]:
                item = {
                    "id": tc.get("id"),
                    "type": "function_call",
                    "status": "completed",
                    "name": tc["function"]["name"],
                    "arguments": json_dumps(tc["function"]["arguments"]),
                    "call_id": tc.get("id"),
                }
                if item["name"] in ("shell", "container.exec", "shell_command"):
                    item["type"] = "local_shell_call"
                    try:
                        args = tc["function"]["arguments"]
                        if isinstance(args, str):
                            args = json_loads(args)
                        item["action"] = {
                            "type": "exec",
                            "command": args.get("command", []),
                        }
                    except (ValueError, TypeError, KeyError):
                        pass
                output_items.append(item)

        if message.get("content"):
            output_items.append(
                {
                    "id": f"msg_{int(time.time() * 1000)}",
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "text", "text": message["content"]}],
                }
            )

        resp_obj = {
            "id": f"zai_{z_data.get('id')}",
            "object": "response",
            "created": z_data.get("created"),
            "model": z_data.get("model"),
            "status": "completed",
            "usage": {
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
            },
            "output": output_items,
        }
        handler.wfile.write(json_dumps(resp_obj))

    def handle_compact(self, data: Dict[str, Any], handler: Any) -> None:
        compaction_model = data.get("model", "glm-4.6")

        messages = data.get("input", [])
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
            "max_tokens": config.request_timeout_read,
        }

        auth_header = handler.headers.get("Authorization")
        if not auth_header and config.zai_api_key:
            auth_header = f"Bearer {config.zai_api_key}"

        try:
            with self.session.post(
                self._endpoint(),
                json=payload,
                headers={"Authorization": auth_header} if auth_header else {},
                timeout=(config.request_timeout_connect, config.request_timeout_read),
            ) as resp:
                if resp.status_code != 200:
                    logger.error(f"Compaction request failed: {resp.status_code}")
                    handler.send_error(resp.status_code, resp.text)
                    return

                z_data = resp.json()
                choice = z_data.get("choices", [{}])[0]
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
