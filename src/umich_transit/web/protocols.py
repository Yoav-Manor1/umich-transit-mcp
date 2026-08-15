"""Structural service boundary consumed by the web presentation layer."""

from typing import Any, Protocol


class WebTransitService(Protocol):
    """Data operations required by the public dashboard."""

    def find_stops(
        self,
        query: str = "",
        near: tuple[float, float] | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]: ...

    async def get_arrivals(
        self,
        *,
        stop_id: str,
        route_id: str | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]: ...

    def prediction_accuracy(
        self, route_id: str | None = None,
    ) -> dict[str, Any]: ...

    def readiness(self) -> dict[str, Any]: ...
