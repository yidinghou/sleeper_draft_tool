#!/usr/bin/env python3
"""Serve the queue builder so the pairs can be answered on a phone.

Two hundred comparisons is couch work, not desk work, but a `file://` page has
no way to hand its answers back. This serves the same page over HTTP and adds
one endpoint each way: the page pushes answers as they accumulate, and the
laptop pulls them down into data/queue-prefs-{season}.json for `--fit`.

Why it serves a prebuilt payload instead of building one. The board it would
need -- data/vorp-snake-{season}.csv and data/adp-{season}.csv -- is gitignored,
so a deploy from git has no board to read. queue_builder.py writes
data/queue-payload-{season}.json, which is committed, and this reads only that
and the template. The VORP pipeline stays on the laptop where its inputs live.

The answers are not the system of record. The phone's localStorage is; this
holds a copy so it can be fetched from somewhere else. A container filesystem
does not survive a redeploy, so point PREFS_DIR at a mounted volume if the copy
should outlive one.

Environment:
  QUEUE_TOKEN  required -- shared secret, passed as ?k= on every route
  PORT         listen port (Railway sets this)
  PREFS_DIR    where answers are written (default: data/)

Usage: QUEUE_TOKEN=... python scripts/queue_server.py [--port 8771] [--season 2026]
"""

from __future__ import annotations

import argparse
import hmac
import json
import os
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from html_page import LOCAL_HTML_SKELETON  # noqa: E402
from queue_builder import payload_path, render  # noqa: E402
from vorp.csv_loader import REPO_ROOT  # noqa: E402
from vorp.league.config import SNAKE_CONFIG  # noqa: E402

#: A finished run is ~20 KB. The cap is generous against that and still small
#: enough that the endpoint cannot be used to make the process eat memory.
MAX_BODY = 2 * 1024 * 1024


def prefs_file(season: int) -> Path:
    return Path(os.environ.get("PREFS_DIR", REPO_ROOT / "data" / "snake")) / f"queue-prefs-{season}.json"


def load_page(season: int) -> str:
    """The page, with any answers already on the server folded in as `resume`.

    Reading them back matters on a phone: clearing site data or opening the
    link in a different browser would otherwise start the run from zero even
    though the answers are sitting right here.
    """
    payload = json.loads(payload_path(season).read_text(encoding="utf-8"))
    saved = prefs_file(season)
    if saved.exists():
        payload["resume"] = json.loads(saved.read_text(encoding="utf-8"))
    return LOCAL_HTML_SKELETON.format(fragment=render(payload))


def make_handler(season: int, token: str):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # noqa: A002 -- quiet by default
            pass

        def _authorised(self) -> bool:
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            # compare_digest so a wrong token cannot be recovered a character
            # at a time from response timing.
            return hmac.compare_digest(query.get("k", [""])[0], token)

        def _send(self, code: int, body: bytes, content_type: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _deny(self) -> None:
            self._send(401, b"unauthorised\n", "text/plain; charset=utf-8")

        def do_GET(self) -> None:  # noqa: N802 -- stdlib method name
            path = urllib.parse.urlparse(self.path).path
            # Unauthenticated, and deliberately so: Railway's healthcheck has
            # no token, and this answers nothing about the data.
            if path == "/health":
                self._send(200, b"ok", "text/plain; charset=utf-8")
                return
            if not self._authorised():
                self._deny()
                return
            if path == "/":
                self._send(200, load_page(season).encode("utf-8"), "text/html; charset=utf-8")
            elif path == "/prefs.json":
                saved = prefs_file(season)
                body = saved.read_bytes() if saved.exists() else b'{"comparisons":[]}'
                self._send(200, body, "application/json")
            else:
                self._send(404, b"not found\n", "text/plain; charset=utf-8")

        def do_POST(self) -> None:  # noqa: N802 -- stdlib method name
            if urllib.parse.urlparse(self.path).path != "/prefs":
                self._send(404, b"not found\n", "text/plain; charset=utf-8")
                return
            if not self._authorised():
                self._deny()
                return

            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > MAX_BODY:
                self._send(413, b"body too large\n", "text/plain; charset=utf-8")
                return
            try:
                body = json.loads(self.rfile.read(length))
                comparisons = body["comparisons"]
                if not isinstance(comparisons, list):
                    raise ValueError("comparisons must be a list")
            except (ValueError, KeyError, TypeError) as err:
                self._send(400, f"bad payload: {err}\n".encode(), "text/plain; charset=utf-8")
                return

            # Written whole, then moved into place: a phone that drops the
            # connection mid-push must not leave a half-written file where the
            # answers used to be.
            target = prefs_file(season)
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(body, separators=(",", ":")), encoding="utf-8")
            tmp.replace(target)
            self._send(200, json.dumps({"saved": len(comparisons)}).encode(), "application/json")

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8771)))
    parser.add_argument("--season", type=int, default=SNAKE_CONFIG.season)
    opts = parser.parse_args()

    token = os.environ.get("QUEUE_TOKEN", "")
    if not token:
        # Refused rather than defaulted: the page and the write endpoint are
        # both behind this, and a deploy that silently came up open would be
        # indistinguishable from a working one until someone found the URL.
        sys.exit("QUEUE_TOKEN is not set. Refusing to start an unauthenticated server.")

    if not payload_path(opts.season).exists():
        sys.exit(
            f"No payload at {payload_path(opts.season)}. "
            f"Run: python3 python/scripts/queue_builder.py {opts.season}"
        )

    players = len(json.loads(payload_path(opts.season).read_text(encoding="utf-8"))["players"])
    print(f"Queue builder for {opts.season}: {players} players, answers -> {prefs_file(opts.season)}")
    print(f"  http://127.0.0.1:{opts.port}/?k={token}")
    ThreadingHTTPServer(("0.0.0.0", opts.port), make_handler(opts.season, token)).serve_forever()


if __name__ == "__main__":
    main()
