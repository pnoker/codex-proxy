import os
from dataclasses import dataclass, field
from .exceptions import ConfigurationError


def _validate_port(port_str: str) -> int:
    try:
        port = int(port_str)
        if not (1 <= port <= 65535):
            raise ConfigurationError(f"Port must be between 1 and 65535, got: {port}")
        return port
    except ValueError as e:
        raise ConfigurationError(f"Invalid port value: {port_str}: {e}")


def _validate_url(url: str, name: str) -> str:
    if not url.startswith(("http://", "https://")):
        raise ConfigurationError(
            f"{name} must be a valid URL starting with http:// or https://"
        )
    return url


@dataclass
class Config:
    # Server
    host: str = field(
        default_factory=lambda: os.environ.get("CODEX_PROXY_HOST", "127.0.0.1")
    )
    port: int = field(
        default_factory=lambda: _validate_port(
            os.environ.get("CODEX_PROXY_PORT", "8765")
        )
    )
    # Request timeouts (in seconds)
    request_timeout_connect: int = 10
    request_timeout_read: int = 600
    compaction_temperature: float = 0.1
    compaction_max_tokens: int = 4096

    # Z.AI
    zai_url: str = field(
        default_factory=lambda: _validate_url(
            os.environ.get(
                "CODEX_PROXY_ZAI_URL",
                "https://open.bigmodel.cn/api/coding/paas/v4",
            ),
            "Z.AI URL",
        )
    )
    zai_api_key: str = field(
        default_factory=lambda: os.environ.get("CODEX_PROXY_ZAI_API_KEY", "")
    )
    zai_compaction_model: str = field(
        default_factory=lambda: os.environ.get("CODEX_PROXY_ZAI_COMPACTION_MODEL", "glm-4.6")
    )

    # DeepSeek
    deepseek_url: str = field(
        default_factory=lambda: _validate_url(
            os.environ.get(
                "CODEX_PROXY_DEEPSEEK_URL",
                "https://api.deepseek.com",
            ),
            "DeepSeek URL",
        )
    )
    deepseek_api_key: str = field(
        default_factory=lambda: os.environ.get("CODEX_PROXY_DEEPSEEK_API_KEY", "")
    )
    deepseek_compaction_model: str = field(
        default_factory=lambda: os.environ.get("CODEX_PROXY_DEEPSEEK_COMPACTION_MODEL", "deepseek-chat")
    )

    # Xiaomi
    xiaomi_url: str = field(
        default_factory=lambda: _validate_url(
            os.environ.get(
                "CODEX_PROXY_XIAOMI_URL",
                "https://api.llm.mioffice.cn/v1",
            ),
            "Xiaomi URL",
        )
    )
    xiaomi_api_key: str = field(
        default_factory=lambda: os.environ.get("CODEX_PROXY_XIAOMI_API_KEY", "")
    )
    xiaomi_compaction_model: str = field(
        default_factory=lambda: os.environ.get("CODEX_PROXY_XIAOMI_COMPACTION_MODEL", "mimo-v2.5-pro")
    )

    # Logging
    log_level: str = field(
        default_factory=lambda: os.environ.get("CODEX_PROXY_LOG_LEVEL", "DEBUG").upper()
    )
    debug_mode: bool = field(
        default_factory=lambda: (
            os.environ.get("CODEX_PROXY_DEBUG", "false").lower() == "true"
        )
    )

# Global Config Instance
config = Config()
