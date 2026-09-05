#!/usr/bin/env python3
"""Serve data/ so the live ranking can save straight back into it.

`python3 -m http.server --directory data` already serves the page, but a
browser can only put a download in Downloads, so every save ended in moving a
file by hand -- and a file picker cannot read Downloads either, so every load
was a second trip through a dialog. One PUT route ends both.

Localhost only, and the only thing it will write is queue-snake-{season}.csv --
the canonical ranking, the file queue_export.py writes and draft_auto reads.
Everything else is a plain static server.

This is not queue_server.py. That one serves the *builder* to a phone over the
network behind a token; this serves the live ranking to the laptop it is
running on. Sharing them would mean putting a write route on a public page.

Usage: python3 python/scripts/rank_server.py [--port 8934]
       open http://localhost:8934/live-rank-2026.html
"""

from __future__ import annotations

import argparse
import re
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent.parent / "data"

#: The one file a PUT may write. Anchored, so no path of any shape -- traversal,
#: absolute, a second segment -- reaches the filesystem.
WRITABLE = re.compile(r"queue-snake-\d{4}\.csv")

#: A 157-row queue is ~12 KB. Generous against that, small enough that the
#: route cannot be used to fill the disk.
MAX_BODY = 1024 * 1024


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):  # noqa: A002 -- stdlib name
        pass

    def do_PUT(self) -> None:  # noqa: N802 -- stdlib name
        name = self.path.lstrip("/").split("?")[0]
        if not WRITABLE.fullmatch(name):
            self.send_error(403, "only queue-snake-{season}.csv is writable")
            return
        length = int(self.headers.get("Content-Length") or 0)
        if not 0 < length <= MAX_BODY:
            self.send_error(413, "empty or oversized body")
            return
        body = self.rfile.read(length)
        # Written whole, then moved into place: a dropped connection mid-save
        # must not leave half a queue where the ranking used to be.
        tmp = DATA / (name + ".tmp")
        tmp.write_bytes(body)
        tmp.replace(DATA / name)
        self.send_response(204)
        self.end_headers()
        print(f"saved {name} ({len(body)} bytes)", flush=True)


def demo() -> None:
    ok = "queue-snake-2026.csv"
    assert WRITABLE.fullmatch(ok)
    for bad in ("../secrets.csv", "queue-snake-2026.csv/../x", "/etc/passwd",
                "queue-snake-26.csv", "queue-prefs-2026.json", "queue-snake-2026.csvx"):
        assert not WRITABLE.fullmatch(bad), f"guard let {bad} through"
    print("ok: only queue-snake-{season}.csv is writable")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8934)
    parser.add_argument("--check", action="store_true")
    opts = parser.parse_args()
    if opts.check:
        demo()
        return
    print(f"data/ on http://localhost:{opts.port}/  (PUT saves the ranking)")
    print(f"  http://localhost:{opts.port}/live-rank-2026.html")
    # Loopback only: this route writes to the repo, and nothing about it should
    # be reachable from the network the phone is on.
    ThreadingHTTPServer(("127.0.0.1", opts.port),
                        partial(Handler, directory=str(DATA))).serve_forever()


if __name__ == "__main__":
    main()
