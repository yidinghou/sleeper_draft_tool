# 02 · Seat identity and divisions (FAQ)

### What does this compute?

Who sits in each of the twelve seats, and how the seats group into the league's
divisions for display. Real managers are resolved from the draft when Sleeper
knows them; every seat Sleeper doesn't cover yet is filled with a league member
so the board always looks live. "My seat" and "my division" are inferred from a
configured handle, never entered by hand.

### Why not just show seat numbers until Sleeper names everyone?

Because a mock draft has no league roster at all, and a real draft names nobody
until it seeds — so a bare-number board would be unreadable for exactly the runs
you most want to rehearse on. The point of the board is to look and behave like
the live one before a single real name exists, which means every seat needs a
plausible manager, a division, and a stable place in the layout from the first
render.

### How does it actually work?

Two joins plus a deterministic fill.

`seat_identity` (in `sleeper_client.py`) maps each 0-indexed `seat_id` to a
manager from two sources, joined against the league `users` list:

```
draft.draft_order   ties a seat to a user_id — authoritative, wins conflicts
each pick.picked_by  reveals a seat the moment it drafts, even pre-order
```

`draft_order` comes in two shapes and both are handled: the documented array
`[user_id, ...]` indexed by seat, and the live API's object `{user_id: slot}`
with `slot` 1-indexed. A `user_id` with no matching user is skipped, not guessed.

`random_fill` then composes a full `{seat_id: identity}`: the real pins are kept
exactly, and every other seat draws a league member (`all_members()`) from a
pool shuffled by `random.Random(MOCK_SEED)`. Members already sitting in a real
seat are dropped from the pool, so nobody appears twice. Because the seed is a
fixed int (`20260827`), a given mock lays out identically every run — stable
screenshots and tests. As the draft seeds, real managers overwrite their random
placeholders (`refresh_seat_identity`); pinning a new real seat can reshuffle
the *other* open seats' placeholders, which is correct because they were only
placeholders.

`build_divisions` groups the seats into `DIVISIONS` — my division first, then
the rest in config order, then a trailing "Unassigned" band for any seat that
matches none — and returns `seat_order`, a strict permutation of the seat ids
the template reorders columns by. The per-seat `bids` arrays stay seat-indexed;
only the display order changes.

### How is "my seat" found?

`resolve_my_seat` scans `seat_users` for the seat whose identity matches
`MY_USERNAME` (`yidinghou`), case-insensitively against both `username` and
`display_name` — Sleeper often leaves `username` blank and sets only
`display_name`, so both are checked. If the handle isn't present yet (mock,
replay, or an unseeded draft), `my_seat` keeps its CLI fallback (`--me`, 1-indexed).

### What's the output, precisely?

`seat_users`: `{seat_id: {user_id, username, display_name}}` for all twelve
seats. `divisions`: the ordered bands `{name, index, mine, seats}`, mine first.
`seat_order`: a permutation of the seat ids for column reordering. `my_seat` and
`my_division`: the resolved seat index and its division index. When the whole
league is really seeded, division membership comes from the config username→
division map; until then it auto-splits seats into the configured divisions by
seat order so the bands still render.

### What does that look like in practice?

- **Live seat reveal:** `seat_identity` reads `{"draft_order": {"u1": 1}}` and
  seat 0 becomes that user; a later `picked_by` fills a seat the order didn't
  cover, growing identity as the auction seeds.
- **Username fallback:** a user with `display_name: ""` shows as their
  `username` instead — `seat_identity` never renders an empty label.
- **Worked example:** the mock fixture carries no real Sleeper identity, so all
  twelve seats auto-split into the 3 configured divisions of 4. My seat is index
  2 (`--me 3`), which lands in the first chunk, so `my_division = 0`,
  `divisions[0]["mine"]` is true, and `seat_order` is a full permutation of
  `0..11` — exactly `test_payload_auto_assigns_divisions_in_mock_mode`.

### What if only some seats are known and nothing fills the rest?

Then division grouping falls back to the auto-split-by-seat (there aren't twelve
real managers to route), but "my seat" is still inferred from the one resolved
seat. This is the partially-seeded real draft: `my_seat` tracks the single known
handle while the bands stay evenly split — see
`test_partial_identity_still_auto_assigns_divisions_but_infers_my_seat`. The
wrong answer would be dropping every seat into one "Unassigned" band the moment
identity is incomplete.

### What's the catch?

The random fill is a plausible fiction, not the truth. On a mock or an unseeded
draft the names, divisions, and even which seat is "mine" are seeded guesses —
correct only in that they're stable and non-duplicating. They can and do get
overwritten the instant Sleeper reveals a real manager, so any read taken off a
placeholder seat (its division, its roster) is provisional until the draft seeds.

### How do I bootstrap the division config for a real league?

Run `python scripts/draft_board.py --draft-id <id> --print-seats`. It fetches
the draft's managers and prints, per seat, the 1-indexed slot, `display_name`,
and `username`, then exits — read-only, writes nothing. Copy those usernames
into `DIVISIONS` in `python/vorp/league/config.py`, and re-run it whenever a
manager changes their handle.

---

## Reference

**Depends on:** `python/vorp/sleeper_client.py`'s `seat_identity`;
`python/vorp/league/config.py` for `DIVISIONS`, `MY_USERNAME`, `MOCK_SEED`,
`all_members`, and `division_index_for`. **Implemented in:**
`python/scripts/auction/draft_board.py` — `random_fill`, `build_divisions`,
`refresh_seat_identity`/`assign_mock_identity`/`_set_identity`,
`resolve_my_seat`, and `print_seats`. **Done when:** `random_fill` is a
no-duplicate deterministic permutation that keeps real pins, both `draft_order`
shapes resolve, mine-first grouping is a strict permutation, and an unknown
handle leaves `my_seat` untouched — see
`test_random_fill_is_a_no_dup_deterministic_permutation`,
`test_seat_identity_maps_both_draft_order_shapes`,
`test_build_divisions_orders_mine_first_and_permutes_seats`, and
`test_my_seat_is_inferred_from_the_configured_handle`.

| Input | Description |
| --- | --- |
| `draft.draft_order` | `{user_id: slot}` or `[user_id, ...]`; authoritative seat→manager map |
| pick `picked_by` + `draft_slot` | reveals a seat the moment it drafts, pre-order |
| league `users` | ties `user_id` to `username`/`display_name` (fetched once, cached) |
| `DIVISIONS`, `MY_USERNAME`, `MOCK_SEED` | config: division membership, my handle, fill seed |

| Output | Description |
| --- | --- |
| `seat_users` | `{seat_id: {user_id, username, display_name}}`, all seats filled |
| `divisions` | ordered bands `{name, index, mine, seats}`, my division first |
| `seat_order` | strict permutation of seat ids for column reordering |
| `my_seat` / `my_division` | resolved from `MY_USERNAME`, else the `--me` fallback |
