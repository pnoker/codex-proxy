import os
import json
import logging
import tomllib
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
    config_path: str = os.path.expanduser("~/.config/codex-proxy/config.json")

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

    def __post_init__(self):
        self._load_from_file()
        self._load_codex_toml()

    def _load_from_file(self):
        if not os.path.exists(self.config_path):
            return
        try:
            with open(self.config_path, "r") as f:
                file_config = json.load(f)

                env_overrides = {
                    "host": "CODEX_PROXY_HOST",
                    "zai_api_key": "CODEX_PROXY_ZAI_API_KEY",
                    "zai_url": "CODEX_PROXY_ZAI_URL",
                    "deepseek_api_key": "CODEX_PROXY_DEEPSEEK_API_KEY",
                    "deepseek_url": "CODEX_PROXY_DEEPSEEK_URL",
                    "xiaomi_api_key": "CODEX_PROXY_XIAOMI_API_KEY",
                    "xiaomi_url": "CODEX_PROXY_XIAOMI_URL",
                    "port": "CODEX_PROXY_PORT",
                    "log_level": "CODEX_PROXY_LOG_LEVEL",
                }
                for attr, env_key in env_overrides.items():
                    if not os.environ.get(env_key):
                        setattr(self, attr, file_config.get(attr, getattr(self, attr)))

                if not os.environ.get("CODEX_PROXY_DEBUG"):
                    self.debug_mode = file_config.get("debug_mode", self.debug_mode)

                self.request_timeout_connect = file_config.get(
                    "request_timeout_connect", self.request_timeout_connect
                )
                self.request_timeout_read = file_config.get(
                    "request_timeout_read", self.request_timeout_read
                )
        except Exception as e:
            logging.warning(f"Failed to load config from {self.config_path}: {e}")

    def _load_codex_toml(self):
        """Read ~/.codex/config.toml for the global model.

        Priority: config.toml model > env > default.
        """
        codex_config_path = os.path.expanduser("~/.codex/config.toml")
        if not os.path.exists(codex_config_path):
            return
        try:
            with open(codex_config_path, "rb") as f:
                codex_config = tomllib.load(f)
            model = codex_config.get("model", "")
            if model:
                self.model = model
        except Exception as e:
            logging.warning(
                f"Failed to load codex config from {codex_config_path}: {e}"
            )

    def get_model(self, fallback: str = "") -> str:
        """Return the resolved model name.

        Priority: config.toml model > caller-provided fallback (env/CLI).
        """
        return self.model or fallback

# Global Config Instance
config = Config()
