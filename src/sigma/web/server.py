"""Local-only read-only HTTP server for a SIGMA Explorer static bundle."""
from __future__ import annotations

import contextlib
import errno
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .builder import MARKER

# Explicit types: on Windows, Python's ``mimetypes`` reads the registry, where ``.js``
# is sometimes registered as ``text/plain``.  With ``nosniff`` the browser would then
# refuse to execute app.js and the page would stay empty.
_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".geojson": "application/geo+json",
    ".txt": "text/plain; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml",
}
_IN_USE = {errno.EADDRINUSE, errno.EACCES, 10048, 10013}  # 10048/10013: Windows socket codes
_PORT_ATTEMPTS = 20


class _ExplorerHandler(SimpleHTTPRequestHandler):
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, **_TYPES}

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        super().end_headers()

    def list_directory(self, path):  # noqa: ANN001
        self.send_error(403, "Directory listing is disabled")
        return None

    def log_message(self, format, *args):  # noqa: A002, ANN001
        # Tile and route requests are frequent; report only failed requests.
        if len(args) >= 2 and str(args[1])[:1] in {"4", "5"}:
            super().log_message(format, *args)


def _bind(root: Path, port: int) -> ThreadingHTTPServer:
    """Bind to 127.0.0.1, moving to the next ports when the requested one is unavailable."""
    handler = partial(_ExplorerHandler, directory=str(root))
    candidates = [port] if port == 0 else list(range(port, min(port + _PORT_ATTEMPTS, 65536)))
    last: OSError | None = None
    for candidate in candidates:
        try:
            return ThreadingHTTPServer(("127.0.0.1", candidate), handler)
        except OSError as exc:
            if exc.errno not in _IN_USE and getattr(exc, "winerror", None) not in _IN_USE:
                raise
            last = exc
    raise OSError(f"No free local port between {port} and {candidates[-1]}: {last}")


def serve_bundle(directory: Path | str, *, port: int = 8765, open_browser: bool = True) -> None:
    root = Path(directory).expanduser().resolve()
    if not (root / MARKER).is_file() or not (root / "index.html").is_file():
        raise FileNotFoundError(f"Not a SIGMA Explorer bundle: {root}")
    # Loopback only: published analytical exports are never exposed to the LAN.
    with _bind(root, port) as server:
        url = f"http://127.0.0.1:{server.server_port}/"
        if port and server.server_port != port:
            print(f"Port {port} is not available; using {server.server_port}.", flush=True)
        print(f"SIGMA Explorer: {url}\nSource bundle: {root}\nCtrl+C to stop.", flush=True)
        if open_browser:
            webbrowser.open(url)
        with contextlib.suppress(KeyboardInterrupt):
            server.serve_forever()
