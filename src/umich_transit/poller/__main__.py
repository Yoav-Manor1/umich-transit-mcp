"""Entry point: `python -m umich_transit.poller` / `umich-transit-poller`."""
import asyncio
import logging

import structlog

from umich_transit.config import settings
from umich_transit.poller.runner import run


def _group_is_clean_shutdown(exc: BaseExceptionGroup) -> bool:
    leaves: list[BaseException] = []

    def collect(error: BaseException) -> None:
        if isinstance(error, BaseExceptionGroup):
            for nested in error.exceptions:
                collect(nested)
        else:
            leaves.append(error)

    collect(exc)
    return bool(leaves) and all(
        isinstance(leaf, (KeyboardInterrupt, asyncio.CancelledError)) for leaf in leaves
    )


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

    def handle_failure(exc: BaseException) -> None:
        if isinstance(exc, BaseExceptionGroup) and _group_is_clean_shutdown(exc):
            log.info("poller.stopped")
            return
        log.error("poller.crashed", error_type=type(exc).__name__, exc_info=True)
        raise SystemExit(1) from exc

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        log.info("poller.stopped")  # clean exit on Ctrl+C, no traceback
    except BaseExceptionGroup as exc:
        handle_failure(exc)
    except Exception as exc:
        handle_failure(exc)


if __name__ == "__main__":
    main()
