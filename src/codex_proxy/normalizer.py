import copy
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Responses API enforces max 64 chars on call_id
_MAX_CALL_ID_LEN = 64


def _clamp_call_id(call_id) -> str:
    """Clamp call_id to 64 characters (Responses API limit)."""
    if isinstance(call_id, str) and len(call_id) > _MAX_CALL_ID_LEN:
        return call_id[:_MAX_CALL_ID_LEN]
    return call_id or ""


class RequestNormalizer:
    """Normalizes various wire APIs (like 'responses') to a internal OpenAI-like structure."""

    @staticmethod
    def normalize(data: dict[str, Any]) -> dict[str, Any]:
        """Normalize the request data."""
        data = copy.copy(data)
        messages = []

        # 1. Handle Instructions (System Prompt)
        if "instructions" in data:
            inst = data["instructions"]
            content = ""
            if isinstance(inst, str):
                content = inst
            elif isinstance(inst, list):
                for block in inst:
                    if isinstance(block, str):
                        content += block
                    elif isinstance(block, dict):
                        content += block.get("text", "")
            if content:
                messages.append({"role": "system", "content": content})

        # 2. Handle Input (User Prompts & History)
        if "input" in data:
            inp = data["input"]
            if isinstance(inp, str):
                inp = [inp]

            if isinstance(inp, list):
                for item in inp:
                    if isinstance(item, str):
                        messages.append({"role": "user", "content": item})
                    elif isinstance(item, dict):
                        RequestNormalizer._process_input_item(item, messages)

        # Use the normalized messages
        data["messages"] = messages

        # 2a. Ensure all tool_calls have IDs (some providers require it)
        RequestNormalizer._ensure_tool_call_ids(messages)

        # 2b. Fix missing tool responses — insert empty tool_result if a tool_call
        #     has no corresponding tool result, otherwise providers reject the request
        RequestNormalizer._fix_missing_tool_responses(messages)

        # 3. Handle Responses API specific fields
        data["previous_response_id"] = data.get("previous_response_id")
        data["store"] = data.get("store", False)
        data["metadata"] = data.get("metadata", {})

        # Map tools (flat -> wrapped)
        if "tools" in data:
            data["tools"] = RequestNormalizer._normalize_tools(data["tools"])

        return data

    @staticmethod
    def _process_input_item(item: dict[str, Any], messages: list[dict[str, Any]]) -> None:
        item_type = item.get("type", "message")

        def get_last_assistant():
            if messages and messages[-1]["role"] == "assistant":
                return messages[-1]
            msg = {"role": "assistant", "content": None}
            messages.append(msg)
            return msg

        if item_type in ("message", "agentMessage"):
            role = item.get("role", "user")
            if role == "developer":
                role = "system"

            content_raw = item.get("content")
            content = ""
            reasoning_content = item.get("reasoning_content", "")
            if isinstance(content_raw, str):
                content = content_raw
            elif isinstance(content_raw, list):
                for part in content_raw:
                    if isinstance(part, str):
                        content += part
                    elif isinstance(part, dict):
                        ptype = part.get("type")
                        if ptype in ("input_text", "text", "output_text"):
                            content += part.get("text", "")
                        elif ptype == "reasoning_text":
                            reasoning_content += part.get("text", "")

            if role == "assistant" or role == "model":
                amsg = get_last_assistant()
                if content:
                    amsg["content"] = (amsg["content"] or "") + content
                if reasoning_content:
                    amsg["reasoning_content"] = (
                        amsg.get("reasoning_content") or ""
                    ) + reasoning_content
                if item.get("thought_signature"):
                    amsg["thought_signature"] = item.get("thought_signature")
            else:
                messages.append({"role": role, "content": content or ""})

        elif item_type == "reasoning":
            content_list = item.get("content", [])
            content = ""
            if isinstance(content_list, list):
                for cp in content_list:
                    if isinstance(cp, str):
                        content += cp
                    elif isinstance(cp, dict):
                        content += cp.get("text", "")

            amsg = get_last_assistant()
            amsg["reasoning_content"] = (amsg.get("reasoning_content") or "") + content
            if item.get("thought_signature"):
                amsg["thought_signature"] = item.get("thought_signature")

        elif item_type in (
            "function_call",
            "commandExecution",
            "local_shell_call",
            "fileChange",
            "custom_tool_call",
            "web_search_call",
        ):
            RequestNormalizer._process_tool_call(item, messages, get_last_assistant)

        elif item_type in (
            "function_call_output",
            "commandExecutionOutput",
            "fileChangeOutput",
            "custom_tool_call_output",
            "local_shell_call_output",
            "web_search_call_output",
        ):
            RequestNormalizer._process_tool_output(item, messages)

    @staticmethod
    def _process_tool_call(
        item: dict[str, Any], messages: list[dict[str, Any]], get_last_assistant: Any
    ) -> None:
        call_id = _clamp_call_id(item.get("call_id") or item.get("id")) or f"call_{len(messages)}"
        name = item.get("name")
        item_type = item.get("type")

        if not name:
            if item_type == "commandExecution":
                name = "run_shell_command"
            elif item_type == "local_shell_call":
                name = "local_shell_command"
            elif item_type == "fileChange":
                name = "write_file"
            elif item_type == "web_search_call":
                name = "web_search"

        args = item.get("arguments") or item.get("input") or {}
        if not args and item_type == "web_search_call":
            args = item.get("action") or {}

        if not args:
            if item_type == "commandExecution":
                args = {
                    "command": item.get("command", ""),
                    "dir_path": item.get("cwd", "."),
                }
            elif item_type == "local_shell_call":
                action = item.get("action", {})
                exec_data = action.get("exec", {})
                args = {
                    "command": exec_data.get("command", []),
                    "working_directory": exec_data.get("working_directory"),
                }
            elif item_type == "fileChange":
                changes = item.get("changes", [])
                path = changes[0].get("path") if changes else "unknown"
                args = {"file_path": path}

        if isinstance(args, dict):
            args = json.dumps(args)

        if name:
            amsg = get_last_assistant()
            if "tool_calls" not in amsg:
                amsg["tool_calls"] = []
            amsg["tool_calls"].append(
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": name, "arguments": args},
                }
            )

            it_sig = item.get("thought_signature")
            it_th = item.get("thought")
            if it_sig:
                amsg["thought_signature"] = it_sig
            if it_th:
                amsg["reasoning_content"] = (amsg.get("reasoning_content") or "") + it_th

    @staticmethod
    def _process_tool_output(item: dict[str, Any], messages: list[dict[str, Any]]) -> None:
        call_id = _clamp_call_id(item.get("call_id") or item.get("id"))
        output_raw = item.get("output") or item.get("content") or item.get("stdout", "")

        content = ""
        if isinstance(output_raw, str):
            content = output_raw
        elif isinstance(output_raw, dict):
            content = output_raw.get("content", "")
            if not content and output_raw.get("success") is False:
                content = "Error: Tool execution failed"
        elif isinstance(output_raw, list):
            for part in output_raw:
                if isinstance(part, str):
                    content += part
                elif isinstance(part, dict) and part.get("type") in (
                    "input_text",
                    "text",
                    "output_text",
                ):
                    content += part.get("text", "")

        if not content and item.get("stderr"):
            content = f"Error: {item['stderr']}"
        messages.append({"role": "tool", "tool_call_id": call_id, "content": content})

    @staticmethod
    def _ensure_tool_call_ids(messages: list[dict[str, Any]]) -> None:
        """Ensure every tool_call has an id field.

        Some providers reject requests where tool_calls lack an id.
        """
        for msg in messages:
            for tc in msg.get("tool_calls", []):
                if not tc.get("id"):
                    tc["id"] = f"call_{id(tc) & 0xFFFFFFFF:08x}"

    @staticmethod
    def _fix_missing_tool_responses(messages: list[dict[str, Any]]) -> None:
        """Insert empty tool results for any tool_call that has no matching response.

        Many providers reject requests where a tool_call is not followed by a
        corresponding tool result message.
        """
        # Collect all tool_call_ids that have a matching tool result
        result_ids = set()
        for msg in messages:
            if msg.get("role") == "tool" and msg.get("tool_call_id"):
                result_ids.add(msg["tool_call_id"])

        # Find orphaned tool_calls and insert empty responses
        insertions = []
        for msg in messages:
            for tc in msg.get("tool_calls", []):
                tc_id = tc.get("id")
                if tc_id and tc_id not in result_ids:
                    insertions.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc_id,
                            "content": "",
                        }
                    )
                    result_ids.add(tc_id)  # avoid duplicates

        if insertions:
            messages.extend(insertions)

    @staticmethod
    def _ensure_tool_call_ids(messages: list[dict[str, Any]]) -> None:
        """Ensure every tool_call has an id field.

        Some providers reject requests where tool_calls lack an id.
        """
        for msg in messages:
            for tc in msg.get("tool_calls", []):
                if not tc.get("id"):
                    tc["id"] = f"call_{id(tc) & 0xFFFFFFFF:08x}"

    @staticmethod
    def _fix_missing_tool_responses(messages: list[dict[str, Any]]) -> None:
        """Insert empty tool results for any tool_call that has no matching response.

        Many providers reject requests where a tool_call is not followed by a
        corresponding tool result message.
        """
        result_ids = set()
        for msg in messages:
            if msg.get("role") == "tool" and msg.get("tool_call_id"):
                result_ids.add(msg["tool_call_id"])

        insertions = []
        for msg in messages:
            for tc in msg.get("tool_calls", []):
                tc_id = tc.get("id")
                if tc_id and tc_id not in result_ids:
                    insertions.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc_id,
                            "content": "",
                        }
                    )
                    result_ids.add(tc_id)

        if insertions:
            messages.extend(insertions)

    @staticmethod
    def normalize_for_compact(data: dict[str, Any]) -> dict[str, Any]:
        """Normalize a compaction request.

        Compaction uses Responses API input[] format but needs Chat Completions
        messages[] for the upstream provider. If the data already has messages[]
        (i.e., already in Chat Completions format), return as-is.
        """
        data = copy.copy(data)

        # If already has messages[] and no input[], it's already normalized
        if "messages" in data and "input" not in data:
            return data

        messages = []

        instructions = data.get("instructions", "")
        if isinstance(instructions, str) and instructions:
            messages.append({"role": "system", "content": instructions})

        inp = data.get("input", [])
        if isinstance(inp, str):
            messages.append({"role": "user", "content": inp})
        elif isinstance(inp, list):
            for item in inp:
                if isinstance(item, str):
                    messages.append({"role": "user", "content": item})
                elif isinstance(item, dict):
                    RequestNormalizer._process_input_item(item, messages)

        data["messages"] = messages
        return data

    @staticmethod
    def _normalize_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized_tools = []
        for t in tools:
            if t.get("type") == "function" and "function" not in t:
                normalized_tools.append(
                    {
                        "type": "function",
                        "function": {
                            "name": t.get("name"),
                            "description": t.get("description"),
                            "parameters": t.get("parameters"),
                            "strict": t.get("strict", False),
                        },
                    }
                )
            else:
                normalized_tools.append(t)
        return normalized_tools
