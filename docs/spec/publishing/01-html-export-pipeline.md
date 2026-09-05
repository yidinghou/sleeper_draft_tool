# 01 · HTML export pipeline (FAQ)

> **Doesn't match current code.** This spec describes `write_pair(fragment,
> out_dir, stem, page_dir=..., page_stem=...)` writing a tracked `pages/`
> local copy alongside the gitignored `artifacts/` fragment. The real
> `python/artifact/html_page.py::write_pair` only takes `(fragment, out_dir,
> stem)` and writes **both** files into the same `out_dir` — which every
> caller passes as `artifacts/`, entirely gitignored. There is no `pages/`
> directory in the repo. Treat the `page_dir`/`page_stem` split and the
> tracked-`pages/` framing below as the intended target design, not what's
> shipped, until the pipeline is updated to match (or this doc is corrected
> to match the pipeline).

### What does the export pipeline produce?

Two files from one page body: a `.artifact.html` **fragment** for the Claude
Artifact host and a standalone `.html` **local page** you can double-click. Each
build script fills a template fragment (`templates/*.html`) with a compact JSON
payload, then hands that string to `write_pair`, which writes both. The fragment
is the publishing intermediate; the local page is the browsable copy.

### Why write two files instead of one?

Because the two destinations want opposite things. The templates in
`templates/` are document *fragments* — `<title>`, `<style>`, markup, `<script>`,
and no `<html>`/`<head>/`<body>` — because that is exactly what the Artifact host
supplies the skeleton for. Open that same fragment as a file:// URL and the
browser has no doctype, so it renders in quirks mode. The local page needs the
skeleton added back; the fragment needs it left out. One writer can't satisfy
both, so `write_pair` emits the fragment verbatim and wraps a copy for local use.

### How does `write_pair` actually work?

It takes the finished fragment string and writes it twice. The fragment goes to
`out_dir` (`artifacts/`, gitignored) as `{stem}.artifact.html`; the local page
goes to `page_dir` (normally the tracked `pages/`) as `{page_stem}.html`, wrapped
in `LOCAL_HTML_SKELETON`:

```python
LOCAL_HTML_SKELETON = """<!doctype html>
<html lang="en">
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
{fragment}
</html>
"""
```

`<head>` and `<body>` are omitted deliberately: the parser opens both on its
own, and hand-writing `<head>` around a fragment that ends in markup would mean
closing it in the right place too. The five skeleton lines are the whole
difference between the two files — the page body is byte-for-byte identical.
`write_pair` returns `(fragment_path, page_path)`: the first is what you hand to
the Artifact tool, the second is what you check in a browser.

### Why does `blended_price.py` use `write_local` instead?

Because it publishes no Artifact — it only writes `pages/blended-price-2026.html`
for local viewing, so it uses the smaller sibling in `python/scripts/html_page.py`.
`write_local` carries the identical `LOCAL_HTML_SKELETON` but skips the fragment
half entirely: one file, no gitignored intermediate. It is the same skeleton
without `write_pair`'s two-destination bookkeeping, for the case where there is
only one destination. (The blended-price model itself is
[`../vorp/04-blended-bar-pricing.md`](../vorp/04-blended-bar-pricing.md).)

### What stops the in-browser model from drifting from the Python one?

`build_seat_value.py --verify`. The seat-value page re-solves the lineup in
JavaScript as you add and drop players — the matching in
`vorp/league/roster_fill.py` exists a second time in the template's script — so
`--verify` re-solves every `PRESET` through the real Python model
(`seat_values`, `price_from_value`) and prints the canonical numbers the page
must reproduce: per preset, how many players agree with the room, how many are
zeroed, the per-position "above the $1 floor" counts, and three sample RB rows.
It also hard-fails the build (`SystemExit`) two ways — if a preset's roster
costs more than the budget can seat (a bankrupt seat bids "out" on everyone and
demonstrates nothing), or if a preset name no longer resolves on the board (a
projection refresh renumbered the players). The seat-value model it guards is
[`../vorp/08-seat-value.md`](../vorp/08-seat-value.md).

### What's the output, precisely?

For `build_seat_value.py`: `artifacts/seat-value-2026.artifact.html` (fragment,
gitignored) and `pages/seat-value-2026.html` (standalone). For
`blended_price.py`: only `pages/blended-price-2026.html`, plus its
`data/blended-price-2026.json`. The build prints each written path and the
fragment size, in KB.

### What does that look like in practice?

- **Publish path:** the fragment carries no skeleton, so the Artifact host wraps
  it and the same bytes render both there and, re-wrapped, from disk.
- **Local path:** `LOCAL_HTML_SKELETON` adds the doctype the file:// URL needs,
  so the page renders in standards mode instead of quirks mode.
- **Worked example:** `--verify` on the `rb-saturated` preset charges the seat
  the room's price for its eight players — $156 of the $200 budget, leaving $37
  of headroom, comfortably above the `$1` floor, so the affordability guard
  passes and the preset re-solves. It then prints that against this roster's
  190.1 bar, Travis Etienne at 189.7 pts prices at `$1` while Jahmyr Gibbs at
  299.9 pts is worth real money — four tenths of a point apart at the bar. Those
  are the exact figures the page's JavaScript has to reproduce.

### What if another build already owns `{stem}.html` in `pages/`?

Pass a distinct `page_stem`. `write_pair` defaults `page_stem` to `stem`, so the
local page and the fragment normally share a name; when two builds would collide
on `pages/{stem}.html`, the second gives its local page its own stem while the
fragment keeps `{stem}.artifact.html`. The wrong assumption is that the fragment
and local names must match — they are independent by design.

### What's the catch?

`--verify` prints the canonical numbers but does not itself run the browser or
diff against the shipped JavaScript. It is a *reference*, not an automated
assertion: it guarantees the Python side is self-consistent and affordable, and
leaves the "does the page agree" comparison to a human reading the two. The hard,
build-breaking failures are only the affordability and name-resolution checks;
a genuine JS/Python divergence in the priced numbers is caught by eye, not by an
exit code.

### How big can a fragment get before the Artifact host rejects it?

The Artifact limit is 16 MB. The seat-value fragment is tens of KB, so it is
never close; the merged draft-demo page (see
[`02-auction-drift-demo.md`](02-auction-drift-demo.md)) is the one that has to
watch its size, and it checks against 16 MB explicitly after the merge.

---

## Reference

**Depends on:** the seat-value model
([`../vorp/08-seat-value.md`](../vorp/08-seat-value.md),
`python/vorp/seat_value.py`) and the blended-bar model
([`../vorp/04-blended-bar-pricing.md`](../vorp/04-blended-bar-pricing.md),
`python/vorp/models.py`); the fragment templates
`python/artifact/templates/seat_value.html` and
`python/scripts/auction/templates/blended_price.html`; `data/projections-2026.csv`.
**Implemented in:** `python/artifact/html_page.py` (`write_pair`,
`LOCAL_HTML_SKELETON`) and its smaller sibling `python/scripts/html_page.py`
(`write_local`); driven by `python/artifact/build_seat_value.py` (with
`--verify`) and `python/scripts/auction/blended_price.py`. **Done when:** a
`build_seat_value.py 2026` run writes both `artifacts/seat-value-2026.artifact.html`
and `pages/seat-value-2026.html` with byte-identical bodies, `--verify` re-solves
every preset without hitting the affordability or name-resolution guard, and
`blended_price.py` writes `pages/blended-price-2026.html` via `write_local`.

| Input | Description |
| --- | --- |
| `fragment` | the template with `__DATA__` replaced by the compact JSON payload |
| `out_dir`, `stem` | where the `.artifact.html` fragment goes, and its name |
| `page_dir`, `page_stem` | where the standalone `.html` goes; both default to the fragment's |
| `PRESETS` | the seat rosters `--verify` re-solves and prices in Python |

| Output | Description |
| --- | --- |
| `{stem}.artifact.html` | publishing fragment, in `artifacts/` (gitignored) — hand this to the Artifact tool |
| `{page_stem}.html` | standalone page, in `pages/`, `LOCAL_HTML_SKELETON`-wrapped |
| `(fragment_path, page_path)` | returned by `write_pair` |
| `--verify` report | per-preset canonical numbers the page's JS must reproduce; `SystemExit` on unaffordable or unresolvable presets |
