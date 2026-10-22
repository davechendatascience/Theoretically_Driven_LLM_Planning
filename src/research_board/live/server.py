"""research-board serve: the board, live, in a browser on this machine (DEF-live-board).

Every board the page receives is one research_board.board.build computed, shaped by board_data, at
the commit and moment it names. The server rebuilds when one of the board's inputs changes -- the
research and evidence ledgers, the stamps, the background runs (their processes included), HEAD and
the declaration files -- and at least every `period` seconds, for the idle clocks and for the
git-ignored files a result is judged against, which no fingerprint sees. It pushes a board only
when it differs from the last one pushed, over Server-Sent Events.

It writes nothing: no record, no declaration, no file, and no git index refresh (every git command
it runs, and the build's, runs with GIT_OPTIONAL_LOCKS=0). It binds 127.0.0.1 unless told otherwise,
answers only requests addressed to it by a loopback name or one allowed with --allow-host, which
stops a page elsewhere in the browser from reading the board through DNS rebinding, and sends a
Content-Security-Policy under which only its own scripts run.
"""

from __future__ import annotations

import ipaddress
import json
import os
import secrets
import subprocess
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

from . import MERMAID, render
from .scouts import OFF, ScoutWatch

LOOPBACK_NAMES = {"localhost", "127.0.0.1", "::1"}
POLL = 2.0                     # seconds between looks at the inputs and the transcripts


def _stat(path: Path) -> tuple[int, int] | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return st.st_size, st.st_mtime_ns


def _head(root: Path) -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True,
                             timeout=30, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip()


def fingerprint(root: Path) -> tuple:
    """What the board is built from, as far as a look can tell without reading it."""
    from component_belief.jobs import jobs
    from research_board import board as B

    belief = root / ".belief"
    runs = sorted((str(j.get("run_id")), str(j.get("state"))) for j in jobs(root))
    return (_stat(B.ledger_path(root)), _stat(belief / "evidence.jsonl"), _stat(belief / "stamps.jsonl"),
            _stat(belief / "artifacts"), tuple(runs), _head(root),
            tuple(_stat(root / name) for name in B._DECLARATION_FILES))


def _same(a: dict[str, Any] | None, b: dict[str, Any]) -> bool:
    """Two boards alike but for when they were built."""
    if a is None:
        return False
    strip = lambda d: {**d, "meta": {k: v for k, v in d["meta"].items() if k not in ("generated_at", "build_seconds")}}
    return strip(a) == strip(b)


class LiveBoard:
    """The latest board and the scouts at work, and the versions the event stream follows."""

    def __init__(self, root: Path, period: float = 15.0, scouts: ScoutWatch | None = None,
                 build: Callable[[Path], Any] | None = None) -> None:
        from research_board import board as B
        from research_board.data import board_data

        self.root, self.period, self.scouts = root, period, scouts
        self._build = build or B.build
        self._data = board_data
        self.cond = threading.Condition()
        self.data: dict[str, Any] | None = None
        self.version = 0
        self.status: dict[str, Any] = {"building": False, "since": None, "error": None, "seconds": None}
        self.status_version = 0
        self.scouts_data: dict[str, Any] = OFF
        self.scouts_version = 0
        self._seen: tuple | None = None
        self._last_build = 0.0

    def _set_status(self, **fields: Any) -> None:
        with self.cond:
            self.status.update(fields)
            self.status_version += 1
            self.cond.notify_all()

    def rebuild(self) -> bool:
        """Build the board once; True when it differs from the last board pushed."""
        self._set_status(building=True, since=time.time())
        began = time.monotonic()
        try:
            data = self._data(self._build(self.root), mode="live")
        except Exception as exc:                          # keep serving the last good board
            self._set_status(building=False, error=f"{type(exc).__name__}: the board could not be built")
            print(f"{datetime.now():%H:%M:%S} build failed: {exc!r}", flush=True)
            return False
        seconds = round(time.monotonic() - began, 2)
        data["meta"]["build_seconds"] = seconds
        changed = not _same(self.data, data)
        with self.cond:
            if changed:
                self.data, self.version = data, self.version + 1
            self.status.update(building=False, error=None, seconds=seconds,
                               checked_at=datetime.now().astimezone().isoformat(timespec="seconds"))
            self.status_version += 1
            self.cond.notify_all()
        return changed

    def tick(self) -> None:
        """One look: rebuild when an input moved or the period ran out; read the transcripts."""
        inputs = fingerprint(self.root)
        now = time.monotonic()
        if self.data is None or inputs != self._seen or now - self._last_build >= self.period:
            self._seen, self._last_build = inputs, now
            if self.rebuild():
                print(f"{datetime.now():%H:%M:%S} board v{self.version}: {self.status['seconds']} s", flush=True)
        if self.scouts is not None:
            found = self.scouts.poll()
            with self.cond:
                if found != self.scouts_data:
                    self.scouts_data, self.scouts_version = found, self.scouts_version + 1
                    self.cond.notify_all()

    def run(self) -> None:
        while True:
            try:
                self.tick()
            except Exception as exc:                      # a bad look is retried, never fatal
                print(f"{datetime.now():%H:%M:%S} {exc!r}", flush=True)
            time.sleep(POLL)


def _allowed(host_header: str, bound: str, extra: set[str]) -> bool:
    """Whether a request's Host names this server: a loopback name when bound to loopback, the
    bound address otherwise, or a name given with --allow-host; any port."""
    host = host_header.strip().lower()
    if host.startswith("["):
        host = host[1:host.find("]")] if "]" in host else host
    elif host.count(":") == 1:
        host = host.split(":", 1)[0]
    if not host:
        return False
    if host in {h.lower() for h in extra}:
        return True
    try:
        loopback = ipaddress.ip_address(bound).is_loopback
    except ValueError:
        loopback = bound.lower() in LOOPBACK_NAMES
    return host in LOOPBACK_NAMES if loopback else host == bound.lower()


def handler(live: LiveBoard, bound: str, extra: set[str]) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args: Any) -> None:
            pass

        def _headers(self, kind: str, length: int | None, csp: str) -> None:
            self.send_header("Content-Type", kind)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", csp)
            if length is not None:
                self.send_header("Content-Length", str(length))
            self.end_headers()

        def _send(self, status: int, body: bytes, kind: str, csp: str = "default-src 'none'") -> None:
            self.send_response(status)
            self._headers(kind, len(body), csp)
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 -- the name http.server calls
            if not _allowed(self.headers.get("Host", ""), bound, extra):
                return self._send(403, b"this board answers only on the address it serves\n", "text/plain; charset=utf-8")
            path = self.path.split("?", 1)[0]
            if path == "/":
                nonce = secrets.token_urlsafe(18)
                with live.cond:
                    data, scouts = live.data, live.scouts_data
                if data is None:
                    return self._send(503, b"the first board is still being built; reload in a moment\n",
                                      "text/plain; charset=utf-8")
                csp = (f"default-src 'none'; script-src 'self' 'nonce-{nonce}'; style-src 'self' 'unsafe-inline'; "
                       "img-src 'self' data:; font-src 'self'; connect-src 'self'; base-uri 'none'; "
                       "form-action 'none'; frame-ancestors 'none'")
                return self._send(200, render(data, scouts, nonce=nonce).encode("utf-8"), "text/html; charset=utf-8", csp)
            if path == "/static/mermaid.min.js":
                return self._send(200, MERMAID.read_bytes(), "text/javascript; charset=utf-8")
            if path == "/board.json":
                with live.cond:
                    data = live.data
                return self._send(200, json.dumps(data, default=str).encode("utf-8"), "application/json")
            if path == "/scouts.json":
                with live.cond:
                    scouts = live.scouts_data
                return self._send(200, json.dumps(scouts, default=str).encode("utf-8"), "application/json")
            if path == "/events":
                return self._events()
            return self._send(404, b"not found\n", "text/plain; charset=utf-8")

        def _events(self) -> None:
            self.send_response(200)
            self.send_header("Connection", "close")
            self._headers("text/event-stream", None, "default-src 'none'")
            self.close_connection = True
            seen = (-1, -1, -1)
            try:
                while True:
                    with live.cond:
                        now = (live.version, live.status_version, live.scouts_version)
                        if now == seen:
                            live.cond.wait(timeout=15)
                            now = (live.version, live.status_version, live.scouts_version)
                        data, status, scouts = live.data, dict(live.status), live.scouts_data
                    out = b""
                    if now[2] != seen[2]:
                        out += b"event: scouts\ndata: " + json.dumps(scouts, default=str).encode() + b"\n\n"
                    if now[1] != seen[1]:
                        out += b"event: status\ndata: " + json.dumps(status).encode() + b"\n\n"
                    if now[0] != seen[0] and data is not None:
                        out += b"event: board\ndata: " + json.dumps(data, default=str).encode() + b"\n\n"
                    seen = now
                    self.wfile.write(out or b": keepalive\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, TimeoutError, OSError):
                return

    return Handler


def start(root: Path, host: str = "127.0.0.1", port: int = 8765, period: float = 15.0,
          allow_hosts: list[str] | None = None, scouts: ScoutWatch | None = None,
          follow: bool = True) -> tuple[ThreadingHTTPServer, LiveBoard]:
    """The server and its board, the first board built; `follow` starts the loop that keeps it current."""
    os.environ["GIT_OPTIONAL_LOCKS"] = "0"            # no git command here refreshes the index
    live = LiveBoard(root, period, scouts)
    live.tick()
    if follow:
        threading.Thread(target=live.run, daemon=True).start()
    server = ThreadingHTTPServer((host, port), handler(live, host, set(allow_hosts or [])))
    server.daemon_threads = True
    return server, live


def serve(root: Path, host: str = "127.0.0.1", port: int = 8765, period: float = 15.0,
          allow_hosts: list[str] | None = None, scouts: ScoutWatch | None = None) -> None:
    server, _ = start(root, host, port, period, allow_hosts, scouts)
    print(f"research board for {root}: http://{'localhost' if host in ('127.0.0.1', '::1') else host}:{port}/",
          flush=True)
    try:
        if not ipaddress.ip_address(host).is_loopback:
            print("  not on loopback: anyone who can reach this address can read the board", flush=True)
    except ValueError:
        pass
    server.serve_forever()
