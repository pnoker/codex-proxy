import json
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import config

logger = logging.getLogger(__name__)

# JSON handling with orjson fallback
try:
    import orjson

    def json_loads(data: bytes | str):
        return orjson.loads(data)

    def json_dumps(data) -> bytes:
        return orjson.dumps(data)
except ImportError:

    def json_loads(data: bytes | str):
        return json.loads(data)

    def json_dumps(data) -> bytes:
        return json.dumps(data).encode("utf-8")


def setup_logging():
    """Configure structured logging."""
    root = logging.getLogger()
    if root.handlers:
        return
    root.setLevel(config.log_level)

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%Y-%m-%dT%H:%M:%SZ"
    )

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)
    root.addHandler(handler)

    log_file = os.environ.get("CODEX_PROXY_LOG_FILE")
    if log_file:
        log_dir = os.path.dirname(log_file)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
        fh = RotatingFileHandler(log_file, maxBytes=10 * 1024 * 1024, backupCount=5)
        fh.setFormatter(formatter)
        root.addHandler(fh)

    # Silence noisy libs
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def create_session(pool_connections=20, pool_maxsize=100) -> requests.Session:
    """Create a robust HTTP session with retries."""
    s = requests.Session()
    retries = Retry(
        total=3,
        backoff_factor=0.1,
        status_forcelist=[502, 503, 504],
        allowed_methods=["HEAD", "GET", "POST", "PUT", "DELETE", "OPTIONS", "TRACE"],
    )
    adapter = HTTPAdapter(
        pool_connections=pool_connections,
        pool_maxsize=pool_maxsize,
        max_retries=retries,
    )
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s
