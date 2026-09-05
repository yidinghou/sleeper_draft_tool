---
name: sleeper-live-draft
description: Draft (and poll) a live or mock Sleeper snake draft using python/scripts/snake/draft_auto.py instead of clicking through the Sleeper UI. Use whenever the user hands over a sleeper.com/draft/nfl/{draft_id} (or sleeper.app, rewrite it) URL and wants it actually drafted — not just inspected. Covers arming, the default fire-after-10s/retry behavior, and resuming a commish-paused draft.
---

# sleeper-live-draft

Draft through `python/scripts/snake/draft_auto.py`, not manual Claude-in-Chrome clicks.
It polls the draft, ranks available players with the real queue-builder ranking
(respecting position caps like at most 1 K / 1 DEF), and sends the pick through
Sleeper's GraphQL endpoint the moment it's your turn. Manual browser clicking is
the fallback only — for reading/inspecting the board, starting the draft, or an
auction draft the script doesn't support.

## Running it

```bash
cd python
python3 scripts/snake/draft_auto.py --selftest        # sanity check before a real draft
python3 scripts/snake/draft_auto.py DRAFT_ID --arm --every 5
```

- `DRAFT_ID` is the numeric id from the URL — `sleeper.app` links are blocked by
  the browser tool, rewrite to `sleeper.com` but the id itself is what the
  script takes, protocol/host don't matter to it.
- `--arm` is required to actually send picks; without it the script only prints
  what it *would* pick (shadow mode). Ask the user before arming against their
  real league draft; a mock is lower-stakes but still confirm if unsure.
- `--arm` needs `$SLEEPER_TOKEN` or `~/.sleeper_token` (a long-lived JWT, see
  `draft_pick.py`'s docstring for how to capture one from DevTools).
- `--every 5` (or lower) polls at least every 5s — comfortably inside any
  "poll every N seconds" ask; the script's own default is `--every 1`.
- Defaults already fire **10 seconds into my turn** (`--fire-after 10`) and
  **retry a rejected send every 5s** (`--retry-every 5`) until it lands or the
  turn moves on — both are baked in, no flags needed unless the user wants a
  different cadence.
- Run it with `run_in_background: true` — it's a long-lived poller, not a
  one-shot command. Check progress with the background-task output file, or
  by hitting `fetch_draft_picks`/`fetch_draft` directly.

## Reading state without the script

`GET https://api.sleeper.app/v1/draft/{draft_id}/picks` (works from a page
context or a plain script) returns every pick with `metadata.first_name` /
`last_name` / `position`, `pick_no`, `draft_slot` — easier than parsing the
board's abbreviated names.

## The one gotcha: commissioner pauses

If the log stalls with lines like `pick N | paused | ...` and no `PICKED` line
follows, the draft was paused (`should_fire` correctly refuses to send into a
pause — this is not a bug). Confirm via a screenshot: look for a "Draft paused
by commish. RESUME" banner at the top of the Sleeper tab, and click RESUME.
The already-running poller picks the "drafting" status back up on its next
tick with no restart needed.

## When to fall back to manual Chrome clicks

- Starting a *new* keeper mock draft (`draftboards/{league_id}` → "New Mock
  Draft") or clicking "START DRAFT" the first time — the script only drives
  an already-started draft.
- Auction drafts — `draft_auto.py` is snake-draft only (`SNAKE_CONFIG`).
- No `$SLEEPER_TOKEN` available and the user doesn't want to set one up for a
  one-off draft.

See the `sleeper-draft-via-claude-in-chrome` memory for the DOM mechanics
(`.player-rank-item2`, `.draft-button:not(.disable)`, etc.) needed in those
fallback cases.
