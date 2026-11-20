# SIGMA Explorer — native Windows launcher

Release filename: **`sigma.exe`** (Windows x64, no terminal, no Python dependency).

## Installation

Copy `sigma.exe` inside an exported SIGMA Explorer folder (the SIGMA package now includes it automatically):

```text
metro_manila-explorer/
├─ sigma.exe
├─ .sigma-explorer
├─ index.html
├─ app.js
├─ data/
└─ vendor/
```

Double-click `sigma.exe` to launch your default browser. Default URL:
`http://localhost:8765/`. If port 8765 is occupied, it tries ports through
8784. The server binds **only** to `127.0.0.1`, rejects foreign `Host` headers,
and does not expose data to the local network.

Right-click the tray icon (sometimes in Windows' overflow/hidden-icons area):

- **Open Explorer**: open another browser tab (a second double-click also does this).
- **Copy Local Link**: copy the *actual* port's localhost URL.
- **Exit SIGMA**: stop the server and remove the tray icon.

Closing a browser tab does not stop the server. To stop it, use the tray menu.

This executable serves *existing* static export files and cannot regenerate
analytical data. Its HTTP server supports GET, HEAD, concurrent asset requests,
common file MIME types and single byte-range requests. Directory listings and
path traversal are blocked. It does not have an external network-listening mode.

SIGMA's Python server normally serves its full `/about.html` from a package
asset that is not copied into the exported bundle. If `about.html`
exists, this native launcher serves it as normal. Otherwise, it provides a brief
About fallback page instead of the original full one.

## Trust and verification

The binary is **not digitally signed**; Windows may show a SmartScreen warning.
Digitally signing a release requires the publisher's trusted code-signing
certificate. This build has not been executed on Windows in the preparation
environment; static PE checks and C-level input validation tests passed.

## Source and build

- `sigma_native.c` — Win32 tray app and static loopback web server.
- `support.c`, `chkstk.s` — minimal, CRT-free helpers.
- `sigma.ico` — original SIGMA branding, extracted losslessly from the preceding launcher.
- `build_resources.py` — embeds all seven icon sizes into native Windows resources.
- `*.def` — Windows OS DLL import declarations.
- `test_safety.py` — exercises path traversal, malformed paths, byte-range overflow,
  foreign `Host` headers, verifies GUI PE format, size, icon and OS-only dependencies.
- `build.sh` — cross-build with fail-fast behavior (`set -euo pipefail`).

To rebuild on Linux with clang and lld-link:

```bash
bash build.sh
```

The build aborts on any compilation, link, or test failure.
