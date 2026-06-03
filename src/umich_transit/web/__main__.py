"""Entry point: `umich-transit-web` — the local bus dashboard.

Starts uvicorn on localhost and opens the page in the default browser.
"""
import threading
import webbrowser

import uvicorn

from umich_transit.web.app import build_app

HOST = "127.0.0.1"
PORT = 8000


def main() -> None:
    url = f"http://{HOST}:{PORT}"
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(build_app(), host=HOST, port=PORT)


if __name__ == "__main__":
    main()
