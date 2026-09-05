---
name: spec-faq
description: Write or rewrite a docs/spec/**.md file as a tight FAQ — short "### Question" headers with 1-4 sentence answers, one worked example, one caveat, and a compact Reference section. Use whenever the user asks to write a new spec, add a spec section, or reformat/tighten an existing spec doc — not for the one-off condensed HTML brief (that's spec-to-brief).
---

# spec-faq

House format for `docs/spec/**.md` files, landed on after A/B testing several
shapes (narrative prose, dialogue, progressive-disclosure tables) against a
verbose FAQ and a tight FAQ. The tight FAQ won; this skill is that format
with the header level restored for scannability. Reference implementation:
`docs/spec/vorp/poc/01-m-faq-mid.md`.

## Shape

```
# <number> · <concept name> (FAQ)

### <Question 1 — what does this compute?>

<1-4 sentences. No throat-clearing, no restating the question.>

### <Question 2 — why not the naive/obvious approach?>

<Name the naive approach, say concretely what it misses.>

### <Question 3 — how does it actually work?>

<The mechanism, in plain terms. This is the one answer allowed to run
long if the mechanism genuinely needs it — but still no filler sentences.>

### <Question 4 — what's the output, precisely?>

<Tie back to Q1's definition.>

### What does that look like in practice?

- **<scenario A>:** <one line, cause → effect>
- **<scenario B>:** <one line, cause → effect>
- **Worked example:** <concrete numbers, one line, ending in the actual
  output value>

### <Edge case question, if one exists — e.g. "what about a position with
no slot at all?">

<State the edge case's output and explicitly name the wrong answer
someone might assume, so the distinction is on the page.>

### What's the catch?

<The one honest limitation of the approach. Every spec has one — find
it, don't skip this section.>

### <Any "does this hold up under X" question relevant to this spec —
live updates, scale, adversarial input, etc., if applicable>

<1-2 sentences.>

---

## Reference

**Depends on:** <upstream files/config>. **Implemented in:** <the file that
owns this logic> (<any shared helper file>). **Done when:** <one sentence,
a concrete pass/fail condition, ideally referencing a fixture>.

| Input | Description |
| --- | --- |
| ... | ... |

| Output | Description |
| --- | --- |
| ... | ... |
```

## Rules

- **Every answer is `### <Question>?` as a real header**, not bolded inline
  text. Headers make the doc scannable and jumpable — that's the whole
  point of FAQ-shaped over narrative-shaped.
- **Tight means 1-4 sentences per answer**, not zero. Cut the sentence that
  restates the question, the transitional "So how does..." throat-clearing,
  and any sentence that only exists to lead into the next one. Keep the
  sentence that states the mechanism or the number.
- **Exactly one worked example**, with real numbers, ending in the actual
  computed value — not "it depends" or "e.g. some value." If the spec has
  no natural worked example, that's a sign the concept isn't concrete
  enough yet; don't skip it, ask for or derive one.
- **Exactly one "what's the catch" question.** Every method trades
  something away. Naming it once, explicitly, is what keeps this format
  honest instead of promotional. Don't bury it inside another answer or
  cut it for space.
- **Question order follows understanding, not implementation order:**
  what it computes → why not the obvious/naive approach → how it actually
  works → what the output means → practice/examples → edge case →
  limitation → (optional) operational question. Reorder only if a spec's
  own logic genuinely demands it.
- **The Reference section is always last, always under one `## Reference`
  header, never collapsed behind `<details>`.** It's the implementation
  contract — `Depends on` / `Implemented in` / `Done when`, then Input and
  Output tables. Keep it out of the FAQ body entirely; nothing above `---`
  should read like a spec contract.
- **No mermaid diagrams, no comparison tables in the FAQ body.** If a
  concept needs a diagram to land, that's a sign to add one more FAQ
  question instead — describe the mechanism in the answer prose. The
  Reference tables are the only tables in the document.
- **Don't add sections this template doesn't have** — no "Old way vs new
  way" table, no progressive-disclosure `### Text` / `### Table` labels,
  no narrative framing paragraph before the first question. Those were
  tried (see `docs/spec/vorp/poc/`) and this FAQ shape beat them.

## When rewriting an existing spec into this format

Read the full source first. Preserve every scenario, number, and edge
case — this is a reformat for readability, not a content cut (that's
`spec-to-brief`'s job, and it produces a separate companion doc, not a
replacement). Pull the honest limitation out of wherever it's currently
buried and give it its own "What's the catch?" question if it doesn't
already have one.
