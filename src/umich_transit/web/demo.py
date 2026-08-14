"""One-command deterministic local showcase."""
import threading
import webbrowser
from pathlib import Path

import uvicorn
from fastapi import FastAPI

from umich_transit.core.demo import build_demo_service
from umich_transit.web.app import build_app

HOST = "127.0.0.1"
PORT = 8000
DEMO_DATABASE_URL = "sqlite:///./data/demo-transit.db"


def build_demo_app(database_url: str = DEMO_DATABASE_URL) -> FastAPI:
    service, _engine = build_demo_service(database_url)
    return build_app(service, demo_mode=True)


def main() -> None:
    Path("data").mkdir(exist_ok=True)
    url = f"http://{HOST}:{PORT}"
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(build_demo_app(), host=HOST, port=PORT)


if __name__ == "__main__":
    main()
