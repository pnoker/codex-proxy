import json
import logging
import re
import socket
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from typing import Dict

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
            body = json.dumps(_ui.get_current_config()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
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
            self.send_error(500, "Internal server error")

    def _handle_post(self):
        logger.info(f"POST {self.path}")

        # Config UI save endpoint
        if self.path == "/config":
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
        if config.debug_mode:
            logger.debug(f"RAW REQUEST: {body.decode('utf-8', errors='replace')}")

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
            provider.handle_request(data, self)

        self.close_connection = True

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
