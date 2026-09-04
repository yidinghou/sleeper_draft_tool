# The live draft board — WIP

> **Work in progress.** The pricing core this board would run on,
> `python/vorp/board.py` (`price_board`), is implemented — see
> [`../vorp/07-live-draft-board.md`](../vorp/07-live-draft-board.md). The
> **server** itself is not: none of `python/vorp/sleeper_client.py`,
> `python/scripts/auction/draft_board.py`, or the `board_slides.html` deck exist in
> this repo yet, on any branch. Expect this whole spec directory to be
> revised as the server gets built.

## What this is

The live draft board is the surface a manager actually watches during an
auction: a single Python server that polls the draft, reprices every remaining
player against the money and slots still in the room, and serves a three-slide
web deck that renders the result. It is the largest thing built on top of the
pricing core — but it adds **no** valuation of its own.

The board is a thin renderer over `../vorp/07-live-draft-board.md`'s server-side
repricing. Every dollar on the page comes from a `price_board` solve in one
Python process; the browser holds no model. What this module owns is everything
*around* that solve: getting live picks in, deciding who sits where, shaping the
payload, drawing the deck, and letting you scrub back through the draft. If you
want the pricing math — how a sale moves a bar, why the pool reconciles — read
`../vorp/07` and the `../vorp/` chain it sits on. If you want to know how the
draft gets into the model and onto the screen, read on.

## How the pieces fit

Picks arrive three ways — a local mock file, a polled Sleeper draft, or an
inline paste — and ingestion turns them into a residual `LeagueState`. Seat
identity resolves who sits in each seat (real managers where Sleeper knows them,
deterministic placeholders where it doesn't) and groups them into divisions. The
rendering contract is the `/state.json` payload and the deck that consumes it.
The scrubber replays any prefix of the draft as a frozen, memoized frame. All
four are one server process, `python/scripts/auction/draft_board.py`.

## The specs

| | What it covers |
| --- | --- |
| [01 · Live data ingestion](01-live-data-ingestion.md) | The three source modes, fingerprint-gated polling, append-only bid-ladder reconstruction, durable draft + offline replay, and the HTTP endpoints |
| [02 · Seat identity and divisions](02-seat-identity-and-divisions.md) | Resolving managers from `draft_order`/`picked_by`, deterministic `random_fill` for open seats, my-seat inference, and division grouping |
| [03 · The rendering contract](03-rendering-contract.md) | The `/state.json` payload shape and the three-slide deck it drives — with no model in the browser |
| [04 · The time-travel scrubber](04-time-travel-scrubber.md) | `get_payload_upto(n)`, prefix-signature frame memoization, the disk cache, warmer threads, and the scrubber UI |
| [Reproduction guide](guide.md) | Rebuild order, exact run commands, the test command, what the fixtures pin, and the gotchas |

Runs on `../vorp/07-live-draft-board.md` (the pricing core) and the `../vorp/`
models it depends on; consumes `../league/index.md` for the residual league state.
