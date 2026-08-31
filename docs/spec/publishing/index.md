# HTML publishing

## What this covers

How a Python valuation model becomes a shareable, self-contained web page. The
models under [`../vorp/`](../vorp/index.md) are pure logic — they print tables
and write JSON, but a table can't show that the same player is worth different
amounts to different seats, or that one sale reprices the whole board. So this
layer ships the model's inputs into an HTML template whose JavaScript re-solves
in the browser, and exports it two ways at once:

1. **A standalone local page** — the template fragment wrapped in a minimal
   document skeleton, so it renders in standards mode from a `file://` URL.
   The spec below describes this as a checked-in `pages/` copy; today it lands
   in gitignored `artifacts/` alongside the fragment — see the correction atop
   [`01-html-export-pipeline.md`](01-html-export-pipeline.md).
2. **An optional Artifact fragment** in `artifacts/` (gitignored) — the same
   page body with no `<html>`/`<head>`/`<body>`, because the Claude Artifact
   host supplies that skeleton itself. This is the copy handed to the publishing
   tool.

`write_pair` writes both from one fragment string; the smaller `write_local`
writes just the standalone page for models that publish no Artifact. The whole
concern is keeping the browser port faithful to the Python model — which is why
the seat-value build re-solves every preset in Python (`--verify`) and the
draft-demo build asserts its template-extraction anchors and its shared opening
board before it merges.

## The specs

| | What it covers |
| --- | --- |
| [01 · HTML export pipeline](01-html-export-pipeline.md) | `write_pair`/`write_local`, the fragment-vs-standalone split, and `--verify` as a model-parity guard |
| [02 · Auction-drift demo](02-auction-drift-demo.md) | four scripted mispricing scenarios replayed through `draft_demo.py`'s own repricing, folded into one tabbed page by build-time template extraction |
| [Reproduction guide](guide.md) | prerequisites, exact build commands, expected outputs, and gotchas |

Exports the models in [`../vorp/08-seat-value.md`](../vorp/08-seat-value.md)
(the seat-value page) and [`../vorp/04-blended-bar-pricing.md`](../vorp/04-blended-bar-pricing.md)
(the blended-price page). The auction-drift demo's repricing conceptually
mirrors [`../vorp/07-live-draft-board.md`](../vorp/07-live-draft-board.md) (WIP,
not yet implemented) but is its own logic in `python/scripts/draft_demo.py`,
not a shared module.
