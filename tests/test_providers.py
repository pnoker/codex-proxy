"""Unit tests for provider registry and routing."""

import pytest
from codex_proxy.server import PROVIDERS
from codex_proxy.providers.base import BaseProvider
from codex_proxy.providers.zai import ZAIProvider
from codex_proxy.providers.deepseek import DeepSeekProvider
from codex_proxy.providers.xiaomi import XiaomiProvider


class TestProviderRegistry:
    def test_all_providers_registered(self):
        assert "zai" in PROVIDERS
        assert "deepseek" in PROVIDERS
        assert "xiaomi" in PROVIDERS

    def test_provider_types(self):
        assert isinstance(PROVIDERS["zai"], ZAIProvider)
        assert isinstance(PROVIDERS["deepseek"], DeepSeekProvider)
        assert isinstance(PROVIDERS["xiaomi"], XiaomiProvider)


class TestBaseProvider:
    def test_base_provider_is_abstract(self):
        with pytest.raises(TypeError):
            BaseProvider()

    def test_handle_compact_default_implementation(self):
        class MockHandler:
            def send_error(self, code, message):
                pass

        # ZAIProvider overrides handle_compact, so this should work
        # But BaseProvider's default sends 501
        class MinimalProvider(BaseProvider):
            def handle_request(self, data, handler):
                pass

        mp = MinimalProvider()
        mock_handler = MockHandler()
        # Default implementation calls send_error(501)
        mp.handle_compact({}, mock_handler)


class TestProviderInstances:
    def test_zai_provider_creation(self):
        provider = ZAIProvider()
        assert isinstance(provider, BaseProvider)

    def test_deepseek_provider_creation(self):
        provider = DeepSeekProvider()
        assert isinstance(provider, BaseProvider)

    def test_xiaomi_provider_creation(self):
        provider = XiaomiProvider()
        assert isinstance(provider, BaseProvider)
