"""Vercel and ASGI entry point for the public transit showcase."""

from umich_transit.web.runtime import build_runtime_app

app = build_runtime_app()
