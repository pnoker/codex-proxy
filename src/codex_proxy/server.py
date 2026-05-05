import json
import logging
import re
import socket
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from typing import Dict

from pathlib import Path

from .config import config
from .exceptions import ProxyError, ProviderError, ValidationError
from .providers.base import BaseProvider
from .providers.zai import ZAIProvider
from .providers.deepseek import DeepSeekProvider
from .providers.xiaomi import XiaomiProvider
from .normalizer import RequestNormalizer
from .utils import json_loads
from .validator import RequestValidator
from . import ui as _ui

logger = logging.getLogger(__name__)

# Provider registry: name -> provider instance
PROVIDERS: Dict[str, BaseProvider] = {
    "zai": ZAIProvider(),
    "deepseek": DeepSeekProvider(),
    "xiaomi": XiaomiProvider(),
}

# Path pattern: /{provider}/v1/responses[/compact]
_PROVIDER_PATH_RE = re.compile(
    r"^/([a-z][a-z0-9]*)/v1/responses(/compact)?$"
)

_CUSTOM_MODELS_PATH = Path(__file__).resolve().parent.parent.parent / "scripts" / "custom_models.json"
_custom_models_cache: list | None = None


def _load_custom_models() -> list:
    global _custom_models_cache
    if _custom_models_cache is not None:
        return _custom_models_cache
    if _CUSTOM_MODELS_PATH.exists():
        try:
            with open(_CUSTOM_MODELS_PATH, "r") as f:
                data = json.load(f)
            _custom_models_cache = data.get("models", [])
            logger.info(
                "Loaded %d custom models from %s",
                len(_custom_models_cache),
                _CUSTOM_MODELS_PATH,
            )
        except Exception as e:
            logger.warning("Failed to load custom_models.json: %s", e)
            _custom_models_cache = []
    else:
        _custom_models_cache = []
    return _custom_models_cache


_MODELS_PATH_RE = re.compile(r"^/(?:[a-z][a-z0-9]*/)?v1/models$")


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def server_bind(self):
        super().server_bind()
        try:
            self.socket.setsockopt(
                socket.IPPROTO_TCP, socket.TCP_NODELAY, 1
            )
        except OSError:
            pass


class ProxyRequestHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        if self.path in ("/", "/ui"):
            body = _ui.get_html()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/config":
            if not self._check_config_auth():
                return
            body = json.dumps(_ui.get_current_config()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif _MODELS_PATH_RE.match(self.path.rstrip("/")):
            self._handle_models()
        else:
            self.send_error(404, "Not found")

    def do_POST(self):
        try:
            self._handle_post()
        except ValidationError as e:
            logger.error(f"Validation error: {e}", exc_info=True)
            self.send_error(400, str(e))
        except ProviderError as e:
            logger.error(f"Provider error: {e}", exc_info=True)
            self.send_error(502, str(e))
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.error(f"Invalid request: {e}", exc_info=True)
            self.send_error(400, f"Invalid request: {e}")
        except ProxyError as e:
            logger.error(f"Proxy error: {e}", exc_info=True)
            self.send_error(500, str(e))
        except Exception as e:
            logger.critical(f"Unexpected error: {e}", exc_info=True)
            try:
                self.send_error(500, "Internal server error")
            except Exception:
                logger.critical("Could not send error response (headers already sent)")

    def _handle_post(self):
        logger.info(f"POST {self.path}")

        # Config UI save endpoint
        if self.path == "/config":
            if not self._check_config_auth():
                return
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length) if content_length else b"{}"
            try:
                data = json_loads(body)
                result = _ui.apply_and_save(data)
                resp = json.dumps(result).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)
            except (ValueError, TypeError) as e:
                err = json.dumps({"error": str(e)}).encode("utf-8")
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(err)))
                self.end_headers()
                self.wfile.write(err)
            return

        # Match provider path pattern
        match = _PROVIDER_PATH_RE.match(self.path.rstrip("/"))
        if not match:
            self.send_error(404, f"Endpoint {self.path} not supported.")
            return

        provider_name = match.group(1)
        is_compact = match.group(2) == "/compact"

        if provider_name not in PROVIDERS:
            self.send_error(404, f"Unknown provider: {provider_name}")
            return

        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            self.send_error(400, "Empty body")
            return

        body = self.rfile.read(content_length)

        try:
            data = json_loads(body)
        except (json.JSONDecodeError, ValueError) as e:
            raise ValidationError(f"Invalid JSON: {e}")

        RequestValidator.validate_request(data, self.path)

        # Attach context headers
        data["_headers"] = {
            "session_id": self.headers.get("session_id"),
            "x-openai-subagent": self.headers.get("x-openai-subagent"),
            "x-codex-turn-state": self.headers.get("x-codex-turn-state"),
            "x-codex-personality": self.headers.get("x-codex-personality"),
        }

        provider = PROVIDERS[provider_name]

        if is_compact:
            provider.handle_compact(data, self)
        else:
            data = RequestNormalizer.normalize(data)
            data["_is_responses_api"] = True
            self._log_request(provider_name, data)
            provider.handle_request(data, self)

        self.close_connection = True

    def _check_config_auth(self) -> bool:
        token = config.config_token
        if not token:
            return True
        auth = self.headers.get("Authorization", "")
        if auth == f"Bearer {token}":
            return True
        self.send_error(403, "Forbidden: invalid or missing config token")
        return False

    @staticmethod
    def _log_request(provider_name: str, data: dict) -> None:
        messages = data.get("messages", [])
        tools = data.get("tools", [])
        parts = [
            "[%s] %s stream=%s msgs=%d tools=%d"
            % (
                provider_name,
                data.get("model", "?"),
                data.get("stream", False),
                len(messages),
                len(tools),
            )
        ]
        for msg in messages:
            role = msg.get("role", "?")
            tc = msg.get("tool_calls")
            if tc:
                names = ",".join(c["function"]["name"] for c in tc if "function" in c)
                parts.append("%s: >>%s" % (role, names))
            else:
                content = msg.get("content") or ""
                parts.append("%s: %s" % (role, content.replace("\n", "\\n")))
        if tools:
            names = ",".join(
                t.get("function", {}).get("name", t.get("name", "?"))
                for t in tools
            )
            parts.append("tools=[%s]" % names)
        logger.info(" | ".join(parts))

    def _handle_models(self):
        custom_models = _load_custom_models()
        models = [
            {"id": m["slug"], "object": "model", "created": 0, "owned_by": "custom"}
            for m in custom_models
        ]
        body = json.dumps({"object": "list", "data": models}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers", "Content-Type, Authorization"
        )
        self.end_headers()

    def log_message(self, format, *args):
        pass


def run_server():
    server_address = (config.host, config.port)
    httpd = ThreadedHTTPServer(server_address, ProxyRequestHandler)
    logger.info(f"Listening on {config.host}:{config.port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down")
        httpd.server_close()


if __name__ == "__main__":
    run_server()
