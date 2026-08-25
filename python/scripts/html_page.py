"""Shared by the HTML exports: wraps a template fragment in the document
skeleton a local file needs.

Templates in `templates/` are fragments -- title, style, markup, script, no
<html>/<head>/<body> -- so this adds those back, or the browser renders in
quirks mode.
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


def write_local(fragment: str, data_dir, stem: str) -> None:
    """Write the standalone local page."""
    (data_dir / f"{stem}.html").write_text(
        LOCAL_HTML_SKELETON.format(fragment=fragment), encoding="utf-8"
    )
