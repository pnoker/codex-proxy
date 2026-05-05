from typing import Any, Dict, Optional

import requests

from .base_stream import BaseStreamHandler


def stream_responses_loop(
    resp: requests.Response,
    handler: Any,
    model: str,
    created_ts: int,
    request_metadata: Optional[Dict[str, Any]] = None,
) -> None:
    stream_handler = BaseStreamHandler(
        handler,
        model,
        created_ts,
        request_metadata,
        provider_name="Xiaomi",
    )
    stream_handler.process_stream(resp)
