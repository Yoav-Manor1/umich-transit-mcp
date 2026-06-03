"""Entry point: `python -m umich_transit.poller` / `umich-transit-poller`."""
import asyncio
import logging

import structlog

from umich_transit.config import settings
from umich_transit.poller.runner import run


def main() -> None:
    logging.basicConfig(level=settings.log_level)
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
    )
    asyncio.run(run())


if __name__ == "__main__":
    main()
