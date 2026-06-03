"""Entry point: `python -m umich_transit.poller` / `umich-transit-poller`."""
import asyncio
import logging

import structlog

from umich_transit.config import settings
from umich_transit.poller.runner import run


def main() -> None:
    logging.basicConfig(level=settings.log_level)
    # Quiet httpx/httpcore: their INFO logs print full request URLs, which for
    # BusTime include the API key as a query param. Keep them at WARNING so the
    # key never lands in logs and the poller output stays readable.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
    )
    log = structlog.get_logger(__name__)
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        log.info("poller.stopped")  # clean exit on Ctrl+C, no traceback


if __name__ == "__main__":
    main()
