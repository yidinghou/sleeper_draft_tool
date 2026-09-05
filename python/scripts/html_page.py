"""Shared by the HTML exports: the document skeleton a local file needs and
a published Artifact doesn't.

Templates in `templates/` are document *fragments* -- title, style, markup,
script, no <html>/<head>/<body> -- because that's what publishing as an
Artifact expects; the host supplies the skeleton. Opening the same fragment
as a local file needs it back, or the browser renders in quirks mode.
"""

from __future__ import annotations

#: <head> and <body> tags are omitted deliberately, not forgotten: the parser
#: opens both, and hand-writing <head> around a fragment that ends in markup
#: would mean closing it in the right place too.
LOCAL_HTML_SKELETON = """<!doctype html>
<html lang="en">
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
{fragment}
</html>
"""


def write_pair(fragment: str, data_dir, stem: str) -> None:
    """Write the Artifact fragment and the standalone local page side by side."""
    (data_dir / f"{stem}.artifact.html").write_text(fragment, encoding="utf-8")
    (data_dir / f"{stem}.html").write_text(
        LOCAL_HTML_SKELETON.format(fragment=fragment), encoding="utf-8"
    )
