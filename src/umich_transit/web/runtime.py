"""Runtime selection for local, demo, and deployed web applications."""

from typing import Literal, cast

AppMode = Literal["local", "demo", "live"]


def resolve_app_mode(configured: str | None, *, on_vercel: bool) -> AppMode:
    """Validate the configured application mode.

    Local development preserves the historical default. Vercel deployments
    must opt into demo or live behavior explicitly so they cannot silently
    launch against ephemeral local storage.
    """
    if configured is None:
        if on_vercel:
            raise ValueError("TRANSIT_APP_MODE is required on Vercel")
        return "local"
    if configured not in {"local", "demo", "live"}:
        raise ValueError("TRANSIT_APP_MODE must be local, demo, or live")
    return cast(AppMode, configured)
