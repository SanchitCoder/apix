"""A loopback-only HTTP server that replays recorded fixtures.

``config/sources.yaml`` enables exactly one source right now: ``fixture_replay``, at
domain ``localhost``, ``legal_basis: FIXTURE``, restricted to paths under
``/fixtures/``. Every real airline/OTA source ships ``NOT_REVIEWED``/disabled pending
legal review (CLAUDE.md guardrail 3) — so until that review lands, this is the only
thing a spider is allowed to fetch from.

This server exists so that fetch still goes through
``apix_core.policy.PolicyEngine.request`` for real: a genuine (loopback-only) HTTP
request, checked, rate-limited and logged by the real policy engine, landing on bytes
recorded from a real capture rather than a live site. No packet ever reaches an actual
external host, which is what "CI must never hit the network" means here — the network
being the live internet, not the loopback interface a test process talks to itself
over.

Uses only :mod:`http.server` — never an HTTP *client* — so it does not trip the
egress-only AST scan in ``tests/test_egress_only.py``.
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import TracebackType
from urllib.parse import unquote, urlsplit

_CONTENT_TYPES = {".json": "application/json", ".html": "text/html; charset=utf-8"}
_DEFAULT_CONTENT_TYPE = "application/octet-stream"


def _make_handler(fixtures_root: Path) -> type[BaseHTTPRequestHandler]:
    resolved_root = fixtures_root.resolve()

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            path = unquote(urlsplit(self.path).path)
            if not path.startswith("/fixtures/"):
                self.send_error(404, "only /fixtures/ paths are served")
                return
            relative = path.removeprefix("/fixtures/").lstrip("/")
            target = (resolved_root / relative).resolve()
            try:
                target.relative_to(resolved_root)
            except ValueError:
                self.send_error(403, "path escapes the fixtures directory")
                return
            if not target.is_file():
                self.send_error(404, f"no fixture at {relative!r}")
                return
            body = target.read_bytes()
            self.send_response(200)
            self.send_header(
                "Content-Type", _CONTENT_TYPES.get(target.suffix, _DEFAULT_CONTENT_TYPE)
            )
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            pass  # a fixture replay is not worth stderr noise in every collect-once run

    return _Handler


class FixtureServer:
    """Serves ``fixtures_root`` under ``/fixtures/`` on an OS-assigned loopback port.

    Use as a context manager; ``base_url`` is only valid once started.
    """

    def __init__(self, fixtures_root: Path) -> None:
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(fixtures_root))
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        """The ``/fixtures`` root URL, at a host matching the ``fixture_replay`` source."""
        port = self._httpd.server_address[1]
        return f"http://localhost:{port}/fixtures"

    def start(self) -> FixtureServer:
        self._thread.start()
        return self

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=5.0)

    def __enter__(self) -> FixtureServer:
        return self.start()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.stop()


__all__ = ["FixtureServer"]
