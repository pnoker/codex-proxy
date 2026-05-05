import logging

from .utils import setup_logging

logger = logging.getLogger(__name__)


def main():
    """Entry point for the codex-proxy server."""
    setup_logging()
    logger.info("Starting codex-proxy...")
    from .server import run_server

    run_server()


if __name__ == "__main__":
    main()
