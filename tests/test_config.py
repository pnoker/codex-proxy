"""Unit tests for configuration management."""

import pytest
from codex_proxy.config import Config, ConfigurationError


class TestConfigDefaults:
    def test_default_host(self):
        cfg = Config()
        assert cfg.host == "127.0.0.1"

    def test_host_from_env(self, monkeypatch):
        monkeypatch.setenv("CODEX_PROXY_HOST", "0.0.0.0")
        cfg = Config()
        assert cfg.host == "0.0.0.0"

    def test_default_port(self):
        cfg = Config()
        assert 1 <= cfg.port <= 65535

    def test_default_urls(self):
        cfg = Config()
        assert cfg.zai_url.startswith("http")
        assert cfg.deepseek_url.startswith("http")
        assert cfg.xiaomi_url.startswith("http")

    def test_default_timeouts(self):
        cfg = Config()
        assert cfg.request_timeout_connect == 10
        assert cfg.request_timeout_read == 600


class TestConfigValidation:
    def test_invalid_port_string_raises_error(self, monkeypatch):
        monkeypatch.setenv("CODEX_PROXY_PORT", "invalid")
        with pytest.raises(ConfigurationError):
            Config()

    def test_port_out_of_range_raises_error(self, monkeypatch):
        monkeypatch.setenv("CODEX_PROXY_PORT", "99999")
        with pytest.raises(ConfigurationError):
            Config()

    def test_invalid_url_raises_error(self, monkeypatch):
        monkeypatch.setenv("CODEX_PROXY_ZAI_URL", "not-a-url")
        with pytest.raises(ConfigurationError):
            Config()

    def test_invalid_deepseek_url_raises_error(self, monkeypatch):
        monkeypatch.setenv("CODEX_PROXY_DEEPSEEK_URL", "ftp://bad")
        with pytest.raises(ConfigurationError):
            Config()


class TestConfigEnvOverrides:
    def test_port_from_env(self, monkeypatch):
        monkeypatch.setenv("CODEX_PROXY_PORT", "9999")
        cfg = Config()
        assert cfg.port == 9999

    def test_zai_url_from_env(self, monkeypatch):
        custom_url = "https://custom.z.ai/api"
        monkeypatch.setenv("CODEX_PROXY_ZAI_URL", custom_url)
        cfg = Config()
        assert cfg.zai_url == custom_url

    def test_deepseek_url_from_env(self, monkeypatch):
        custom_url = "https://custom.deepseek.com"
        monkeypatch.setenv("CODEX_PROXY_DEEPSEEK_URL", custom_url)
        cfg = Config()
        assert cfg.deepseek_url == custom_url

    def test_xiaomi_url_from_env(self, monkeypatch):
        custom_url = "https://custom.xiaomi.com/v1"
        monkeypatch.setenv("CODEX_PROXY_XIAOMI_URL", custom_url)
        cfg = Config()
        assert cfg.xiaomi_url == custom_url

    def test_log_level_from_env(self, monkeypatch):
        monkeypatch.setenv("CODEX_PROXY_LOG_LEVEL", "WARNING")
        cfg = Config()
        assert cfg.log_level == "WARNING"

    def test_debug_mode_from_env(self, monkeypatch):
        monkeypatch.setenv("CODEX_PROXY_DEBUG", "false")
        cfg = Config()
        assert cfg.debug_mode is False

    def test_api_key_from_env(self, monkeypatch):
        monkeypatch.setenv("CODEX_PROXY_ZAI_API_KEY", "test-key")
        cfg = Config()
        assert cfg.zai_api_key == "test-key"

        monkeypatch.setenv("CODEX_PROXY_DEEPSEEK_API_KEY", "ds-key")
        cfg = Config()
        assert cfg.deepseek_api_key == "ds-key"

        monkeypatch.setenv("CODEX_PROXY_XIAOMI_API_KEY", "xm-key")
        cfg = Config()
        assert cfg.xiaomi_api_key == "xm-key"
