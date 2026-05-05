import time
import logging
import requests
from typing import Dict, Any, Optional

from ..utils import json_dumps, json_loads

logger = logging.getLogger(__name__)


class XiaomiStreamHandler:
    """Maps Xiaomi SSE stream to Codex Responses API events."""

    def __init__(
        self,
        handler: Any,
        model: str,
        created_ts: int,
        request_metadata: Optional[Dict[str, Any]] = None,
    ):
        self.handler = handler
        self.model = model
        self.created_ts = created_ts
        self.request_metadata = request_metadata or {}
        self.resp_id = f"resp_{created_ts}"
        self.seq_num = 0

        self.full_content = ""
        self.full_reasoning = ""
        self.reasoning_item: Optional[Dict[str, Any]] = None
        self.reasoning_idx: int = -1
        self.message: Optional[Dict[str, Any]] = None
        self.message_idx: int = -1
        self.idx: int = 0

        self.tool_calls: Dict[int, Dict[str, Any]] = {}

    def _send_event(self, evt_type: str, data: Dict[str, Any]) -> None:
        self.seq_num += 1
        event = {
            "id": f"evt_{int(time.time() * 1000)}_{self.seq_num}",
            "object": "response.event",
            "type": evt_type,
            "created_at": int(time.time()),
            "sequence_number": self.seq_num,
            **data,
        }
        payload = (
            b"event: " + evt_type.encode() + b"\ndata: " + json_dumps(event) + b"\n\n"
        )
        self.handler.wfile.write(payload)
        self.handler.wfile.flush()

    def process_stream(self, resp: requests.Response) -> None:
        response_obj = {
            "id": self.resp_id,
            "object": "response",
            "created_at": self.created_ts,
            "model": self.model,
            "status": "in_progress",
            "temperature": self.request_metadata.get("temperature", 1.0),
            "top_p": self.request_metadata.get("top_p", 1.0),
            "tool_choice": self.request_metadata.get("tool_choice", "auto"),
            "tools": self.request_metadata.get("tools", []),
            "parallel_tool_calls": True,
            "store": self.request_metadata.get("store", True),
            "metadata": self.request_metadata.get("metadata", {}),
            "output": [],
        }

        self._send_event("response.created", {"response": response_obj})

        try:
            for line in resp.iter_lines():
                if not line or not line.startswith(b"data: "):
                    continue
                if line == b"data: [DONE]":
                    break
                self._handle_line(line[6:])
        except Exception as e:
            logger.error(f"Error in Xiaomi stream processing: {e}")
        finally:
            self._finalize(response_obj)

    def _handle_line(self, json_data: bytes) -> None:
        try:
            data = json_loads(json_data)
            logger.debug(f"Xiaomi STREAM DELTA: {data}")

            choices = data.get("choices", [])
            if not choices:
                return
            choice = choices[0]
            delta = choice.get("delta", {})

            if "tool_calls" in delta:
                for tc_delta in delta["tool_calls"]:
                    idx = tc_delta.get("index", 0)
                    if idx not in self.tool_calls:
                        output_idx = self.idx
                        self.idx += 1
                        call_id = (
                            tc_delta.get("id")
                            or f"call_{int(time.time() * 1000)}_{output_idx}"
                        )

                        tool_call = {
                            "id": call_id,
                            "type": "function_call",
                            "status": "in_progress",
                            "name": "",
                            "arguments": "",
                            "call_id": call_id,
                        }
                        self.tool_calls[idx] = {
                            "item": tool_call,
                            "index": output_idx,
                        }

                        self._send_event(
                            "response.output_item.added",
                            {
                                "response_id": self.resp_id,
                                "output_index": output_idx,
                                "item": tool_call,
                            },
                        )

                    tc = self.tool_calls[idx]["item"]
                    fn_delta = tc_delta.get("function", {})
                    if "name" in fn_delta:
                        tc["name"] += fn_delta["name"]
                    if "arguments" in fn_delta:
                        args_part = fn_delta["arguments"]
                        if isinstance(args_part, dict):
                            args_part = json_dumps(args_part)
                        tc["arguments"] += args_part

            # Handle reasoning content as separate item
            reasoning = delta.get("reasoning_content") or ""
            if reasoning:
                self.full_reasoning += reasoning

                if self.reasoning_item is None:
                    self._init_reasoning()

                self._send_event(
                    "response.reasoning_summary_text.delta",
                    {
                        "response_id": self.resp_id,
                        "item_id": self.reasoning_item_id,
                        "output_index": self.reasoning_idx,
                        "summary_index": 0,
                        "delta": reasoning,
                    },
                )
                if self.reasoning_item:
                    self.reasoning_item["summary"][0]["text"] = self.full_reasoning

            # Handle content (actual response text)
            content = delta.get("content") or ""
            if content:
                self.full_content += content

                if self.message is None:
                    self._init_message()

                self._send_event(
                    "response.output_text.delta",
                    {
                        "response_id": self.resp_id,
                        "item_id": self.item_id,
                        "output_index": self.message_idx,
                        "content_index": 0,
                        "delta": content,
                    },
                )
                if self.message:
                    self.message["content"][0]["text"] = self.full_content

        except Exception as e:
            logger.debug(f"Failed to parse Xiaomi stream line: {e}")

    def _init_reasoning(self) -> None:
        self.reasoning_idx = self.idx
        self.idx += 1
        self.reasoning_item_id = f"rs_{int(time.time() * 1000)}_{self.reasoning_idx}"
        self.reasoning_item = {
            "id": self.reasoning_item_id,
            "type": "reasoning",
            "status": "in_progress",
            "summary": [{"type": "summary_text", "text": ""}],
        }
        self._send_event(
            "response.output_item.added",
            {
                "response_id": self.resp_id,
                "output_index": self.reasoning_idx,
                "item": self.reasoning_item,
            },
        )

    def _init_message(self) -> None:
        self.message_idx = self.idx
        self.idx += 1
        self.item_id = f"msg_{int(time.time() * 1000)}_{self.message_idx}"
        self.message = {
            "id": self.item_id,
            "type": "message",
            "role": "assistant",
            "status": "in_progress",
            "content": [{"type": "output_text", "text": ""}],
        }
        self._send_event(
            "response.output_item.added",
            {
                "response_id": self.resp_id,
                "output_index": self.message_idx,
                "item": self.message,
            },
        )

    def _finalize(self, response_obj: Dict[str, Any]) -> None:
        items_to_close = []
        if self.reasoning_item:
            items_to_close.append((self.reasoning_idx, self.reasoning_item))
        if self.message:
            items_to_close.append((self.message_idx, self.message))
        for tc_data in self.tool_calls.values():
            items_to_close.append((tc_data["index"], tc_data["item"]))

        items_to_close.sort(key=lambda x: x[0])

        final_output = []
        for out_idx, item in items_to_close:
            item["status"] = "completed"

            if item.get("type") == "function_call":
                if item["name"] in ("shell", "container.exec", "shell_command"):
                    item["type"] = "local_shell_call"
                    try:
                        args = json_loads(item["arguments"])
                        item["action"] = {
                            "type": "exec",
                            "command": args.get("command", []),
                        }
                    except (ValueError, TypeError, KeyError):
                        pass

            self._send_event(
                "response.output_item.done",
                {"response_id": self.resp_id, "output_index": out_idx, "item": item},
            )
            final_output.append(item)

        response_obj.update(
            {
                "status": "completed",
                "completed_at": int(time.time()),
                "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
                "output": final_output,
            }
        )

        self._send_event("response.completed", {"response": response_obj})


def stream_responses_loop(
    resp: requests.Response,
    handler: Any,
    model: str,
    created_ts: int,
    request_metadata: Optional[Dict[str, Any]] = None,
) -> None:
    stream_handler = XiaomiStreamHandler(handler, model, created_ts, request_metadata)
    stream_handler.process_stream(resp)
