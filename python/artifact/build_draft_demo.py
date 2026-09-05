#!/usr/bin/env python3
"""Fold the four draft-demo scenario pages into one publishable Artifact.

`scripts/auction/draft_demo.py` writes five local pages: a landing page and one page
per scenario, cross-linked by relative filename. That works from the
filesystem and not at all as an Artifact, where every page is its own URL and
`href="draft-demo-2026-panic-run.html"` resolves to nothing. On a phone it is
also just the wrong shape -- nobody wants to hold five links.

So this builds one page with the four scenarios behind a tab bar. It does
*not* re-solve anything: it reads the JSON `draft_demo.py` already wrote, which
keeps a four-minute solve out of a build that should take a second, and
guarantees the artifact shows exactly the numbers the local pages do.

Nor does it fork the template. The stylesheet, the markup and the ~450 lines
of render logic are lifted out of `scripts/auction/templates/draft_demo.html` at build
time and re-hosted inside `templates/scenario_shell.html`, so a change to the
scenario page shows up here on the next build. Four anchors hold that together
and every one of them is asserted -- if the template moves, this fails loudly
rather than emitting a broken page.

The scenarios share an opening board, so `players` is hoisted out of the four
payloads and stored once; that is most of what keeps the merged page near the
size of a single scenario rather than four times it.

Usage: python artifact/build_draft_demo.py [season] [--out=artifacts]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from artifact.html_page import write_pair  # noqa: E402
from vorp.csv_loader import REPO_ROOT  # noqa: E402
from vorp.league.config import LEAGUE_CONFIG  # noqa: E402

SOURCE_TEMPLATE = (
    Path(__file__).resolve().parent.parent / "scripts" / "templates" / "draft_demo.html"
)
SHELL_TEMPLATE = Path(__file__).resolve().parent / "templates" / "scenario_shell.html"

#: The scenario page's IIFE, and the markup and stylesheet it renders into.
#: Each of these appears exactly once in the source template; `_cut` enforces
#: that, because a silently-missed anchor would produce a page that loads and
#: does nothing.
STYLE_END = "</style>"
MARKUP_START = '<div class="wrap">'
DATA_TAG = '<script id="demo-data" type="application/json">'
IIFE_START = "  (function () {"
IIFE_END = "  })();"

#: Navigation the merged page replaces with its tab bar. Both are dropped
#: rather than left dangling at a filename no Artifact URL will ever have.
BACK_LINK_MARKUP = '    <a class="back-link" id="back-link" href="#">&larr; All scenarios</a>\n'
BACK_LINK_SCRIPT = (
    '    document.getElementById("back-link").href = "draft-demo-" + D.season + ".html";\n'
)

#: The scenario page reads its one payload out of the DOM; the merged page
#: passes four of them in as an argument instead. Left in place this line
#: shadows `boot`'s parameter with a read of an element that no longer
#: exists, and every render throws on a null textContent.
DATA_BOOTSTRAP = (
    '    var D = JSON.parse(document.getElementById("demo-data").textContent);\n'
)


def _cut(text: str, anchor: str, what: str) -> int:
    """Index of `anchor`, insisting it appears exactly once."""
    count = text.count(anchor)
    if count != 1:
        raise SystemExit(
            f"{SOURCE_TEMPLATE.name}: expected exactly one {what} anchor "
            f"({anchor!r}), found {count}. The template moved; update "
            f"{Path(__file__).name}."
        )
    return text.index(anchor)


def extract(template: str) -> Dict[str, str]:
    """Pull the scenario page apart into the three pieces the shell re-hosts."""
    style_end = _cut(template, STYLE_END, "stylesheet end") + len(STYLE_END)
    markup_start = _cut(template, MARKUP_START, "markup start")
    data_start = _cut(template, DATA_TAG, "data tag")
    iife_start = _cut(template, IIFE_START, "script start") + len(IIFE_START)
    iife_end = _cut(template, IIFE_END, "script end")

    head = template[:style_end]
    markup = template[markup_start:data_start].rstrip()
    script = template[iife_start:iife_end]

    # The head keeps its <title>, font links and the whole stylesheet, but the
    # shell opens its own <style> for the additions -- so hand back the head
    # with the closing tag trimmed and let the shell close it.
    head = head[: -len(STYLE_END)].rstrip()

    for fragment, name, target in (
        (BACK_LINK_MARKUP, "back-link markup", "markup"),
        (BACK_LINK_SCRIPT, "back-link href", "script"),
        (DATA_BOOTSTRAP, "payload bootstrap", "script"),
    ):
        source = markup if target == "markup" else script
        if source.count(fragment) != 1:
            raise SystemExit(
                f"{SOURCE_TEMPLATE.name}: {name} not found exactly once where "
                f"expected. Update {Path(__file__).name}."
            )
    markup = markup.replace(BACK_LINK_MARKUP, "")
    script = script.replace(BACK_LINK_SCRIPT, "").replace(DATA_BOOTSTRAP, "")

    return {"head": head, "markup": markup, "script": script}


def merge_payloads(season: int, keys: List[str]) -> Dict:
    """One payload from the four the scenario run wrote.

    Everything that is a property of the *board* rather than the scenario --
    the league, the window, the dial, and the 192-row player list with its
    opening prices -- is identical across all four by construction (they start
    from one solved opening board), so it is asserted identical and stored
    once.
    """
    data_dir = REPO_ROOT / "data" / "auction"
    loaded = []
    for key in keys:
        path = data_dir / f"draft-demo-{season}-{key}.json"
        if not path.exists():
            raise SystemExit(
                f"missing {path.relative_to(REPO_ROOT)} -- run "
                f"`python scripts/auction/draft_demo.py {season}` first."
            )
        loaded.append(json.loads(path.read_text()))

    first = loaded[0]
    shared = {k: first[k] for k in ("season", "window", "w_floor", "league", "players")}
    for payload, key in zip(loaded[1:], keys[1:]):
        for field in shared:
            if payload[field] != shared[field]:
                raise SystemExit(
                    f"scenario {key!r} disagrees with {keys[0]!r} on {field!r}; "
                    "the scenarios no longer share one opening board, so they "
                    "cannot share one page. Re-run draft_demo.py for all of them."
                )

    shared["scenarios"] = [
        {
            "key": payload["key"],
            "title": payload["title"],
            "blurb": payload["blurb"],
            "frames": payload["frames"],
            "ledger": payload["ledger"],
        }
        for payload in loaded
    ]
    return shared


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("season", type=int, nargs="?", default=LEAGUE_CONFIG.season)
    parser.add_argument(
        "--out",
        default="artifacts",
        help="output directory, relative to the repo root (default: artifacts)",
    )
    args = parser.parse_args()

    index_path = REPO_ROOT / "data" / "auction" / f"draft-demo-{args.season}.json"
    if not index_path.exists():
        raise SystemExit(
            f"missing {index_path.relative_to(REPO_ROOT)} -- run "
            f"`python scripts/auction/draft_demo.py {args.season}` first."
        )
    keys = [s["key"] for s in json.loads(index_path.read_text())["scenarios"]]

    parts = extract(SOURCE_TEMPLATE.read_text(encoding="utf-8"))
    payload = merge_payloads(args.season, keys)

    fragment = SHELL_TEMPLATE.read_text(encoding="utf-8")
    for marker, value in (
        ("__ORIGINAL_HEAD__", parts["head"]),
        ("__ORIGINAL_MARKUP__", parts["markup"]),
        ("__ORIGINAL_SCRIPT__", parts["script"]),
        ("__DATA__", json.dumps(payload, separators=(",", ":"))),
    ):
        if marker not in fragment:
            raise SystemExit(f"{SHELL_TEMPLATE.name}: missing {marker}")
        fragment = fragment.replace(marker, value)

    out_dir = REPO_ROOT / args.out
    stem = f"draft-demo-{args.season}"
    fragment_path = write_pair(fragment, out_dir, stem)

    size_mb = len(fragment.encode("utf-8")) / 1_000_000
    print(f"Wrote {fragment_path.relative_to(REPO_ROOT)} ({size_mb:.1f} MB)")
    print(f"      {(out_dir / f'{stem}.html').relative_to(REPO_ROOT)} (open locally)")
    print(f"      {len(keys)} scenarios: {', '.join(keys)}")
    if size_mb > 16:
        raise SystemExit("over the 16 MB Artifact limit")


if __name__ == "__main__":
    main()
