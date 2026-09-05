"""The Artifact half of the HTML exports, kept out of `scripts/html_page.py`
on purpose.

`scripts/html_page.py` used to write both -- a `.artifact.html` fragment for
publishing and a `.html` for opening locally -- and a82f533 cut the artifact
half back out when the workflow lapsed. This package is that workflow brought
back without re-entangling it: `scripts/` still writes only local pages, and
everything an Artifact needs lives here.

Templates in `scripts/templates/` are document *fragments* -- title, style,
markup, script, no <html>/<head>/<body> -- because that is exactly what
publishing expects; the host supplies the skeleton. A local file needs the
skeleton back, or the browser renders the fragment in quirks mode.
"""

from __future__ import annotations

from pathlib import Path

#: <head> and <body> are omitted deliberately, not forgotten: the parser opens
#: both, and hand-writing <head> around a fragment that ends in markup would
#: mean closing it in the right place too.
LOCAL_HTML_SKELETON = """<!doctype html>
<html lang="en">
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
{fragment}
</html>
"""


def write_pair(fragment: str, out_dir: Path, stem: str) -> Path:
    """Write the Artifact fragment and a standalone local page beside it.

    Returns the fragment's path -- the one to hand to the Artifact tool. The
    local page is there so the same build can be checked in a browser without
    publishing anything.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    fragment_path = out_dir / f"{stem}.artifact.html"
    fragment_path.write_text(fragment, encoding="utf-8")
    (out_dir / f"{stem}.html").write_text(
        LOCAL_HTML_SKELETON.format(fragment=fragment), encoding="utf-8"
    )
    return fragment_path
