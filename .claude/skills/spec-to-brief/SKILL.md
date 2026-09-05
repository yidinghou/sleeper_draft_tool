---
name: spec-to-brief
description: Condense a wordy docs/spec/**.md file (or a whole spec folder) into a short, click-through local HTML brief — thesis plus condensed scenarios/tradeoffs, one screen at a time via Next/Back, no diagrams or contract tables (those stay in the source) and no long scroll. Use when the user wants a spec, RFC, or design doc turned into something easier to read at a glance, not just re-skinned markdown.
---

# spec-to-brief

Turn one or more verbose markdown specs into a **condensed, visual brief** —
not a re-styled 1:1 render of the same words. The source `.md` stays the
implementation contract (keep every scenario, tradeoff, and correction note
there). The brief is a *different, shorter document* built for someone who
wants the shape of the spec in 30 seconds, with the full text one click or
scroll away if they need it.

## Inputs

- `args` names a target: a single spec file, or a directory of specs (e.g.
  `docs/spec/vorp`). If the user just says "make a brief for X", resolve X
  to a path yourself.
- Default output: `<spec-dir>/brief/<slug>.html`, one HTML file per source
  `.md`, sitting next to (not replacing) the source. If the directory holds
  a numbered series (`00-`, `01-`, `02-…`) that clearly reads as one spec
  with an index doc, offer a single combined brief instead, with each
  source doc as one step in the click-through — ask only if it's genuinely
  ambiguous which the user wants.

## Step 1 — Read and distill, don't transcribe

Read the full source file. Do not pipe it through any mechanical
markdown→HTML converter — condensing *is* the job, and that's a judgment
call only you can make per document. For each source doc, extract:

- **Title + one-sentence thesis** — what does this spec claim, in one
  sentence? Rewrite it; don't lift the opening paragraph verbatim if it's
  longer than a sentence.
- **Scenarios, tradeoffs, correction notes** — compress each Gherkin
  scenario to one line: the situation plus the outcome, not the full
  Given/When/Then. Same for prose tradeoff callouts and "corrected after
  real-data review" notes — one line each: what changed and why it
  matters, not the paragraph. These compressed lines are the highest-value
  content in the brief; don't cut them entirely even though you're
  shortening them.
- **What to drop entirely** — process metadata that only matters to an
  implementer already in the code: "Depends on / Implemented in / Done
  when" headers, restated definitions the reader already has from an
  earlier section, transitional sentences that exist to connect paragraphs
  rather than assert anything.
- **What stays out of the brief on purpose, every time** — mermaid
  diagrams and input/output contract tables. Both are already as compact
  as the source gets; the brief isn't a better rendering of them, it's a
  reason to go open the `.md` and read them there. Mention their existence
  in one clause if useful ("see the contract table in the source for exact
  I/O") but don't reproduce them.

Budget: if the source is N words, the brief's running text should usually
land well under N/3. If you can't get there, you're still transcribing —
cut harder, lean on the diagram and tables to carry weight prose currently
carries.

## Step 2 — Design the page

Load the `artifact-design` skill and follow its process for this page:
write the short color/type/layout plan it asks for, calibrated as a
**document treatment** (per that skill's "Read the request first" section)
— polished, real hierarchy, generous whitespace, not a landing-page hero.
Ground the palette and type pairing in *this spec's specific subject*, not
a reused look — a previous brief's palette is not a template to copy
forward; rederive the plan each time so the result stays specific to what
the doc is actually about.

Apply the artifact-design fundamentals regardless of output destination:
both-theme tokens (light default at bare `:root`, dark under
`prefers-color-scheme` and `[data-theme]`), a real type scale, Google
Fonts only (or a system stack), `overflow-x: auto` on wide content, no
lorem, no template clichés.

**Progressive disclosure, not a long scroll.** One section is visible at a
time; the reader advances with an explicit action, not by scrolling past
it. Concretely: each source doc (or, within a long doc, each natural
sub-section — thesis, then scenarios) is its own screen. Show exactly one,
hide the rest (don't just anchor-scroll to them — a hidden section should
not be reachable by scrolling past the visible one). Give the reader:
- a **Next / Back** control to step linearly, and
- a persistent index (sidebar or top stepper) that jumps straight to any
  section, showing which one is current

Keep the step transition instant or a quick fade — this is a document, not
a slideshow, so don't over-produce the motion. Respect
`prefers-reduced-motion`.

## Step 3 — Write the file, don't auto-publish

Write the finished page directly with the Write tool. This is a **local
companion file**, not an Artifact — do not call the Artifact tool unless
the user separately asks to publish it. Tell the user the path and open it
for them (`open <path>` on macOS) so they can look without asking.

## Multiple docs in one run

If asked to brief a whole folder, repeat Step 1 per document but derive the
design plan *once* and apply it across the whole run, so the set reads as
one coherent brief (consistent palette/type), the same way the source docs
read as one spec series. Prefer one combined click-through page over
several separate files when there's an index doc tying the series
together — each source doc becomes one step, with the persistent index
still showing all steps and which one is current.
