"""
PRIVEX desktop entry point (also the PyInstaller entry).

Starts the local server on 127.0.0.1 and opens the UI in the default browser.
If an instance is already running it just opens the browser.
"""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser


def _already_running(url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{url}/api/health", timeout=1) as r:
            return r.status == 200
    except Exception:
        return False


def _port_free(host: str, port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex((host, port)) != 0


def _setup_logging(data_dir) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [
        logging.handlers.RotatingFileHandler(data_dir / "privex.log", maxBytes=2_000_000, backupCount=2,
                                             encoding="utf-8"),
    ]
    if sys.stdout is not None:            # windowed builds have no console
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(level=logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def main() -> None:
    # Windowed (console=False) builds have no stdio; libraries that print progress would crash.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")

    ap = argparse.ArgumentParser(description="PRIVEX local privacy firewall")
    ap.add_argument("--no-browser", action="store_true", help="don't open the UI")
    ap.add_argument("--port", type=int, help="port (default 8765 or $PRIVEX_PORT)")
    ap.add_argument("--no-tray", action="store_true", help="run in the foreground without a tray icon")
    args = ap.parse_args()
    if args.port:
        os.environ["PRIVEX_PORT"] = str(args.port)

    from privex_core.config import settings
    _setup_logging(settings.data_dir)
    log = logging.getLogger("privex")
    url = f"http://{settings.host}:{settings.port}"

    if _already_running(url):
        log.info("PRIVEX already running at %s", url)
        if not args.no_browser:
            webbrowser.open(url)
        return
    if not _port_free(settings.host, settings.port):
        log.error("Port %d is in use by another program. Set PRIVEX_PORT or use --port.", settings.port)
        sys.exit(1)

    import uvicorn
    from privex_server.app import app

    server = uvicorn.Server(uvicorn.Config(app, host=settings.host, port=settings.port,
                                           log_config=None, access_log=False))
    log.info("PRIVEX %s starting at %s (data: %s)", app.version, url, settings.data_dir)

    if not args.no_browser:
        def open_when_ready():
            for _ in range(120):
                if _already_running(url):
                    webbrowser.open(url)
                    return
                time.sleep(0.5)
        threading.Thread(target=open_when_ready, daemon=True).start()

    tray = None if args.no_tray else _make_tray(url, server)
    if tray is None:
        server.run()
        return
    threading.Thread(target=server.run, daemon=True, name="privex-server").start()
    tray.run()          # blocks until "Quit"


def _make_tray(url: str, server):
    """System-tray icon (Open / Quit). Returns None where no tray is available."""
    try:
        import pystray
        from PIL import Image, ImageDraw
    except Exception:
        return None
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((2, 2, 62, 62), fill=(14, 18, 23, 255), outline=(0, 230, 118, 255), width=4)
    d.polygon([(32, 12), (50, 20), (48, 38), (32, 52), (16, 38), (14, 20)], fill=(0, 230, 118, 255))

    def quit_app(icon, _item):
        server.should_exit = True
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("Open PRIVEX", lambda *_: webbrowser.open(url), default=True),
        pystray.MenuItem(f"Running at {url}", None, enabled=False),
        pystray.MenuItem("Quit", quit_app),
    )
    return pystray.Icon("privex", img, "PRIVEX — local privacy firewall", menu)


if __name__ == "__main__":
    main()
