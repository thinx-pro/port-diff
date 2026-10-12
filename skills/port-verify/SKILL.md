---
name: port-verify
description: Use while porting, rewriting or re-implementing a program (e.g. TypeScript/Go/Zig/C to Rust, Python to Node, a clean-room clone). Before claiming a ported piece is done, run port-diff against the original implementation on real inputs and fix every BREAK/DIFF instead of editing tests or comparison rules to make them pass.
---

# Port verify

The old implementation is the specification. "It compiles" and "the ported tests pass" are not
evidence of equivalence: the tests came from the old code and cover only what someone thought to test.

## Setup (once per port)

1. Find or create a corpus of real inputs in `port-cases/` — one file or directory per case.
   Prefer real-world inputs (sample projects, fixtures from issues, generated edge cases: empty input,
   Unicode, huge input, ties/ordering, invalid input, missing files). Aim for 20+ cases.
2. If the old binary will not stay runnable, record it once:
   `port-diff record --old "<old command> {case}" --cases port-cases --out port-diff-baseline.json`
3. Install if needed: `pipx install git+https://github.com/thinx-pro/port-diff`
   (or `pip install git+https://github.com/thinx-pro/port-diff`).

## Loop (after each ported unit)

Run, and read the JSON:

```bash
port-diff run --old "<old command> {case}" --new "<new command> {case}" --cases port-cases --repeat 3 --json -
```

or, against a recording: `port-diff check --new "<new command> {case}" --cases port-cases --json -`

For every result with verdict `BREAK` or `DIFF`:

- Read `findings[].diff`. Decide whether the old behavior is intended. Default: it is.
- Fix the new implementation, not the case and not the normalization.
- Only add a normalizer (`--norm`, `--sub`) for differences that are genuinely irrelevant
  (timestamps, pointer values, hash-map ordering the old program never promised). When you do,
  write the reason next to the command in `PORTING.md`. Never add `--norm sort-lines` to output
  whose order the old program defines.
- `WARN` with "nondeterministic": the old program itself is flaky on that input; pin seeds/time or
  exclude the case and say so.
- `PERF`: note it; fix if the port's goal included speed.

## Done means

- `port-diff` exits 0 on the full corpus (`--fail-on diff`), and
- the report lists every intentional behavior change (with a reason) in `PORTING.md`.

Report the summary line (e.g. `40 cases · 0 BREAK · 0 DIFF · 3 NOISE · 37 SAME`) when you hand back.
Do not edit `port-cases/` or the baseline file to make a comparison pass.
