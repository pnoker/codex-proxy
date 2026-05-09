"""Integration tests for the proxy server."""

import json
import pytest
from unittest.mock import MagicMock, patch
from codex_proxy.server import ProxyRequestHandler, PROVIDERS


class MockRequest:
    def __init__(self):
        self.rfile = None
        self.wfile = None


class MockServer:
    pass


def create_handler(body_dict, path="/zai/v1/responses"):
    body_bytes = json.dumps(body_dict).encode("utf-8")

    request = MockRequest()
    rfile = MagicMock()
    rfile.read.return_value = body_bytes

    wfile = MagicMock()

    with patch("http.server.BaseHTTPRequestHandler.__init__", return_value=None):
        handler = ProxyRequestHandler(request, ("0.0.0.0", 8888), MockServer())

    handler.rfile = rfile
    handler.wfile = wfile
    handler.headers = {"Content-Length": str(len(body_bytes))}
    handler.request_version = "HTTP/1.1"
    handler.path = path

    handler.send_response = MagicMock()
    handler.send_header = MagicMock()
    handler.end_headers = MagicMock()
    handler.send_error = MagicMock()

    return handler, wfile


class TestRequestRouting:
    """Test request routing to providers by URL path."""

    def test_zai_request_routing(self):
        handler, _ = create_handler(
            {"model": "glm-4", "messages": [{"role": "user", "content": "Hello"}]},
            "/zai/v1/responses",
        )

        with patch.object(PROVIDERS["zai"], "handle_request") as mock_zai:
            handler._handle_post()
            mock_zai.assert_called_once()

    def test_deepseek_request_routing(self):
        handler, _ = create_handler(
            {
                "model": "deepseek-v4-pro",
                "messages": [{"role": "user", "content": "Hello"}],
            },
            "/deepseek/v1/responses",
        )

        with patch.object(PROVIDERS["deepseek"], "handle_request") as mock_ds:
            handler._handle_post()
            mock_ds.assert_called_once()

    def test_xiaomi_request_routing(self):
        handler, _ = create_handler(
            {
                "model": "mimo-v2.5-pro",
                "messages": [{"role": "user", "content": "Hello"}],
            },
            "/xiaomi/v1/responses",
        )

        with patch.object(PROVIDERS["xiaomi"], "handle_request") as mock_xm:
            handler._handle_post()
            mock_xm.assert_called_once()

    def test_unknown_provider_returns_404(self):
        handler, _ = create_handler(
            {"model": "test", "messages": [{"role": "user", "content": "Hello"}]},
            "/unknown/v1/responses",
        )
        handler._handle_post()
        handler.send_error.assert_called_once()
        assert handler.send_error.call_args[0][0] == 404


class TestRequestValidation:
    def test_invalid_json_returns_400(self):
        body_bytes = b"not valid json"

        request = MockRequest()
        rfile = MagicMock()
        rfile.read.return_value = body_bytes
        wfile = MagicMock()

        with patch("http.server.BaseHTTPRequestHandler.__init__", return_value=None):
            handler = ProxyRequestHandler(request, ("0.0.0.0", 8888), MockServer())

        handler.rfile = rfile
        handler.wfile = wfile
        handler.headers = {"Content-Length": str(len(body_bytes))}
        handler.path = "/zai/v1/responses"
        handler.send_error = MagicMock()

        handler.do_POST()
        handler.send_error.assert_called_once()
        assert handler.send_error.call_args[0][0] == 400

    def test_empty_body_returns_400(self):
        handler, _ = create_handler({})
        handler.headers = {"Content-Length": "0"}
        handler._handle_post()
        handler.send_error.assert_called_once()
        assert handler.send_error.call_args[0][0] == 400

    def test_invalid_endpoint_returns_404(self):
        handler, _ = create_handler({"model": "test"}, "/invalid")
        handler._handle_post()
        handler.send_error.assert_called_once()
        assert handler.send_error.call_args[0][0] == 404

    def test_old_v1_endpoint_returns_404(self):
        handler, _ = create_handler(
            {"model": "test"}, "/v1/responses"
        )
        handler._handle_post()
        handler.send_error.assert_called_once()
        assert handler.send_error.call_args[0][0] == 404


class TestCompactionRequests:
    def test_compact_route_uses_correct_provider(self):
        handler, _ = create_handler(
            {
                "model": "glm-4",
                "input": "Long conversation...",
                "instructions": "Summarize",
            },
            "/zai/v1/responses/compact",
        )

        with patch.object(PROVIDERS["zai"], "handle_compact") as mock_compact:
            handler._handle_post()
            mock_compact.assert_called_once()

    def test_compact_deepseek(self):
        handler, _ = create_handler(
            {
                "model": "deepseek-chat",
                "input": "Long conversation...",
                "instructions": "Summarize",
            },
            "/deepseek/v1/responses/compact",
        )

        with patch.object(PROVIDERS["deepseek"], "handle_compact") as mock_compact:
            handler._handle_post()
            mock_compact.assert_called_once()

    def test_compact_validation_error(self):
        """Compact request with empty messages fails validation."""
        handler, _ = create_handler(
            {"model": "test", "messages": "not-a-list"},
            "/zai/v1/responses/compact",
        )

        handler.do_POST()
        handler.send_error.assert_called_once()
        assert handler.send_error.call_args[0][0] == 400


class TestHeaders:
    def test_context_headers_preserved(self):
        handler, _ = create_handler(
            {
                "model": "glm-4",
                "messages": [{"role": "user", "content": "Hello"}],
            },
            "/zai/v1/responses",
        )

        handler.headers = {
            "Content-Length": "100",
            "session_id": "session-123",
            "x-openai-subagent": "true",
            "x-codex-turn-state": "state-456",
            "x-codex-personality": "helpful",
        }

        with patch.object(PROVIDERS["zai"], "handle_request") as mock_handle:
            handler._handle_post()
            call_args = mock_handle.call_args[0]
            data = call_args[0]
            assert "_headers" in data
            assert data["_headers"]["session_id"] == "session-123"
            assert data["_headers"]["x-openai-subagent"] == "true"


class TestResponsesAPI:
    def test_responses_api_flag_set(self):
        handler, _ = create_handler(
            {
                "model": "glm-4",
                "messages": [{"role": "user", "content": "Hello"}],
            },
            "/zai/v1/responses",
        )

        with patch.object(PROVIDERS["zai"], "handle_request") as mock_handle:
            handler._handle_post()
            call_args = mock_handle.call_args[0]
            data = call_args[0]
            assert data.get("_is_responses_api") is True

    def test_compact_no_responses_api_flag(self):
        handler, _ = create_handler(
            {
                "model": "glm-4",
                "input": [{"role": "user", "content": "content"}],
                "instructions": "Summarize",
            },
            "/zai/v1/responses/compact",
        )

        with patch.object(PROVIDERS["zai"], "handle_compact") as mock_handle:
            handler._handle_post()
            call_args = mock_handle.call_args[0]
            data = call_args[0]
            assert data.get("_is_responses_api") is None


class TestErrorHandling:
    def test_validation_error_returns_400(self):
        handler, _ = create_handler(
            {
                "model": "x" * 101,
                "messages": [{"role": "user", "content": "Hello"}],
            },
            "/zai/v1/responses",
        )

        handler.do_POST()
        handler.send_error.assert_called_once()
        assert handler.send_error.call_args[0][0] == 400

    def test_provider_error_returns_502(self):
        from codex_proxy.exceptions import ProviderError

        handler, _ = create_handler(
            {
                "model": "glm-4",
                "messages": [{"role": "user", "content": "Hello"}],
            },
            "/zai/v1/responses",
        )

        with patch.object(
            PROVIDERS["zai"], "handle_request", side_effect=ProviderError("fail")
        ):
            handler.do_POST()
            handler.send_error.assert_called_once()
            assert handler.send_error.call_args[0][0] == 502

    def test_unexpected_error_returns_500(self):
        handler, _ = create_handler(
            {
                "model": "glm-4",
                "messages": [{"role": "user", "content": "Hello"}],
            },
            "/zai/v1/responses",
        )

        with patch(
            "codex_proxy.normalizer.RequestNormalizer.normalize",
            side_effect=Exception("Unexpected error"),
        ):
            handler.do_POST()
            handler.send_error.assert_called_once()
            assert handler.send_error.call_args[0][0] == 500


class TestEndpoints:
    @pytest.mark.parametrize(
        "path",
        [
            "/zai/v1/responses",
            "/deepseek/v1/responses",
            "/xiaomi/v1/responses",
        ],
    )
    def test_valid_responses_endpoints(self, path):
        provider_name = path.split("/")[1]
        handler, _ = create_handler(
            {
                "model": "test-model",
                "messages": [{"role": "user", "content": "Hello"}],
            },
            path=path,
        )

        with patch.object(PROVIDERS[provider_name], "handle_request") as mock_handle:
            handler._handle_post()
            mock_handle.assert_called_once()

    @pytest.mark.parametrize(
        "path",
        [
            "/zai/v1/responses/compact",
            "/deepseek/v1/responses/compact",
            "/xiaomi/v1/responses/compact",
        ],
    )
    def test_valid_compact_endpoints(self, path):
        provider_name = path.split("/")[1]
        handler, _ = create_handler(
            {
                "model": "test-model",
                "input": [{"role": "user", "content": "content"}],
                "instructions": "Summarize",
            },
            path=path,
        )

        with patch.object(PROVIDERS[provider_name], "handle_compact") as mock_handle:
            handler._handle_post()
            mock_handle.assert_called_once()
