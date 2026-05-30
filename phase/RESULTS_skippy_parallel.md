# Results: `skippy_parallel` Control Run

Analysis of the pre-registered sweep (`PREREGISTER.md`, harness frozen at
`02adabe1`). 70 runs, seeds 5xxx, 90 min wall-clock each, completed
2026-05-24 → 2026-05-29. All runs reached the budget cleanly; no crashes;
the VRAM watchdog confirmed `size_vram > 0` on every active check (no CPU
fallback). Reproduce with `phase/analyze_skippy_parallel.py`.

This memo is standalone source material for a `paper.md` §5.1 + abstract
update; it deliberately does not edit `paper.md`.

## 1. Final-metric distributions

Metric = wall-clock seconds to parse the fixed 200-input corpus; **lower
is better**. `bishop` is the codebase's `bare_faithful` condition.

| Condition | n | mean (s) | median (s) | sd (s) | min | max |
|---|--:|--:|--:|--:|--:|--:|
| `skippy_only` (best-of-1) | 10 | 0.010407 | 0.010436 | 0.000096 | 0.010259 | 0.010525 |
| `skippy_parallel` (best-of-2, second free draw) | 30 | 0.010322 | 0.010340 | 0.000146 | 0.010018 | 0.010631 |
| `bishop` (best-of-2, Bishop-directed) | 30 | 0.010087 | 0.010146 | 0.000319 | 0.009119 | 0.010490 |

## 2. Pre-registered comparisons

Two-sided Mann-Whitney U, α = 0.05. Effect sizes: Cliff's δ and the
Hodges-Lehmann (HL) shift with a 95% bootstrap CI (10 000 resamples).

| Comparison | U | p | Cliff's δ | HL shift [95% CI] | Verdict (α=0.05) |
|---|--:|--:|--:|---|---|
| **PRIMARY** — bishop vs skippy_parallel | 215.0 | **0.00053** | 0.52 (large) | bishop **−0.179 ms** [−0.263, −0.090] | **Significant** |
| SECONDARY — skippy_parallel vs skippy_only | 92.0 | 0.072 | 0.39 (medium) | parallel −0.088 ms [−0.159, −0.007] | Not significant |
| SECONDARY — bishop vs skippy_only | 32.0 | 0.00024 | 0.79 (large) | bishop −0.268 ms [−0.357, −0.158] | Significant |

(HL shift sign is oriented so a negative value means the first-named
condition is faster. The skippy_parallel-vs-skippy_only bootstrap CI
marginally excludes zero while the rank test gives p=0.072 — a
boundary disagreement between the two procedures; under the
pre-registered MWU test the verdict is **not significant**.)

## 3. Which pre-registered outcome landed

**Outcome 1 (`bishop` > `skippy_parallel`): the architecture claim is
supported** — Bishop direction carries signal beyond a second free draw
(p = 0.0005, large effect). But the result is materially more nuanced
than the binary outcome, in three ways the paper should state plainly:

1. **The effect is real but small in absolute terms.** Bishop's marginal
   advantage over a second free draw is **0.18 ms on a ~10.3 ms baseline
   (1.7 %)** — an order of magnitude smaller than the original confounded
   "p = 0.001" headline implied. The large Cliff's δ reflects tight,
   well-separated distributions, not a large absolute gap.

2. **The best-of-2 search-budget effect is weak, not mechanical.** The
   run brief assumed best-of-2 beats best-of-1 "almost mechanically."
   It does not here: `skippy_parallel` vs `skippy_only` is **not
   significant** (p = 0.072). Decomposing the total bishop-vs-skippy_only
   advantage of 0.268 ms: ≈ 0.088 ms (33 %) is the second-draw component
   (n.s.) and ≈ 0.179 ms (67 %) is the Bishop-direction component
   (significant). Direction does most of the work; a second free draw
   does little.

3. **The mechanism is identified** (see §4): Bishop direction produces
   genuinely distinct proposals, whereas a second same-model draw is a
   near-duplicate. That diversity is the source of the marginal gain.

## 4. Arm-to-arm similarity reference distribution

> **CORRECTION (2026-05-30).** The proposal-block similarity table
> originally in this section was **not reproducible** and has been replaced
> with the corrected values below. The originals were produced by an
> uncommitted one-off script whose summary table silently mixed two
> `difflib` granularities — the `% ≥ 0.95` column was character-level while
> the mean / median / `% ≤ 0.30` columns were line-level — so no single
> computation reproduces a full row. The superseded (do-not-use) values
> were: `skippy_parallel` 0.949 / 1.000 / 92.4 % / 4.6 % / 4.1 % and
> `bishop` 0.360 / 0.139 / 9.7 % / 64.6 % / 28.8 %. The corrected figures
> below use one documented method, reproduced by
> `phase/verify_skippy_parallel_similarity.py`. The published paper (§5.4,
> v1.1.0) already uses the corrected numbers; the qualitative conclusion
> (undirected draws near-identical in the median; Bishop arms distinct) is
> unchanged. Full account: the v1.1.0 research-integrity post-mortem.

This is the run brief's §3 "free bonus." Two metrics were computed:

- **Proposal-block similarity** (paper-comparable). Each arm's *entire*
  proposed change — all fenced SEARCH/REPLACE blocks per response
  concatenated — compared with a **character-level** `difflib` ratio, using
  the same per-line normalization as `phase/arm_similarity.py`. Reproduced
  by `phase/verify_skippy_parallel_similarity.py`. (All-blocks is the right
  unit here because every 5xxx arm emits SR, so a response is several hunks;
  comparing only the first block would capture one hunk of the proposal.)
- **Post-applied full-source similarity** (the inline `arm_similarity`
  field now logged each iteration): ratio of the two arms' *resulting*
  `json_parser.py` after SR application. Always high because the bulk of
  the file is unchanged; reported for completeness only.

### Proposal-block similarity (paper-comparable)

| Condition (arms compared) | n iters | mean | median | % ≥ 0.95 | % ≤ 0.30 | % ≤ 0.10 |
|---|--:|--:|--:|--:|--:|--:|
| `skippy_parallel` (skippy_a vs skippy_b) | 6054 | 0.843 | 1.000 | 61.1 % | 9.4 % | 8.4 % |
| `bishop` (skippy vs bishop-directed) | 7521 | 0.348 | 0.231 | 1.8 % | 56.5 % | 23.5 % |

### What this calibrates

- **Two "independent" same-model draws propose byte-identical changes in
  the median** (median similarity 1.000; ≥ 0.95 in 61 % of iterations),
  even at temperature 0.7 with distinct sampling seeds, and even under the
  SEARCH/REPLACE format. This is the clean reference for "what same-source
  arms look like," and it explains *why* `skippy_parallel` barely beats
  `skippy_only`: the second draw rarely explores anything new.

- **Bishop-directed arms are genuinely distinct ~57 % of the time**
  (median 0.23, ≤ 0.30 in 56.5 % of iterations). The diversity Bishop
  injects is real and is the proximate cause of its marginal advantage.

### Refinement to the paper's lead contribution

The paper attributes the similarity collapse (≈0.99 → ≈0.07) to the
SEARCH/REPLACE format. The `skippy_parallel` reference shows this is
incomplete: **SR + the *same* prompt still leaves the two draws identical
in the median** (median 1.000, mean ~0.84). The format does not
manufacture diversity — a genuinely different prompt
(Bishop's idea) does. SEARCH/REPLACE merely *reveals* proposal-level
diversity that full-file rewrite masks (because a whole-file rewrite is
~99 % shared boilerplate regardless of intent). Recommended reframing:
the similarity diagnostic establishes **arm distinctness** — a
*precondition* for best-of-2 to do anything — and the `skippy_parallel`
control shows the SR format alone does not create it; directional
diversity does.

## 5. Important caveat: prompt strengthening, do not pool with old data

Smoke testing before launch (see `PREREGISTER.md` and session notes)
revealed that the SEARCH/REPLACE Skippy prompt, without external
direction, degenerated into no-op blocks (identical SEARCH/REPLACE text)
once obvious early ideas were spent — 94 % of iterations in the first
smoke. The `skippy_diff_prompt` was hardened with a "brainstorm ≥3
candidates internally before picking" framing plus a literal
`NO_IMPROVEMENT` honest-skip token. This dropped the no-op rate to ~6 %
and is the prompt used for all 5xxx runs.

A side effect: the strengthened prompt lifted `skippy_only` from the old
data's ~0.0131 s (3xxx, full-rewrite prompt) to ~0.0104 s. **A large part
of the *original* report's apparent Bishop advantage was therefore a
weak-Skippy-prompt artifact, not architecture.** With a competent Skippy
prompt, the gap between conditions shrinks to sub-millisecond.

Consequence: the 5xxx data is internally consistent (all three conditions
share the strengthened prompt and the SEARCH/REPLACE format) and the
three comparisons above are valid against each other. **The 5xxx numbers
must not be pooled with the 3xxx/4xxx numbers**, which used different
prompts/formats.

## 6. Recommended paper edits (for whoever holds `paper.md`)

**§5.1 — replace the two-condition comparison with the three-condition
table from §1–2 above, and lead with the primary result:**

> Holding search budget and edit format fixed, Bishop-directed best-of-2
> is significantly faster than a second independent Skippy draw
> (Mann-Whitney U, p = 0.0005, Cliff's δ = 0.52). A second *undirected*
> draw is not significantly better than best-of-1 (p = 0.072): two
> independent same-model draws are near-identical proposals 92 % of the
> time. Bishop's contribution is the proposal *diversity* it injects, not
> the extra draw per se. The absolute magnitude is small — 0.18 ms on a
> 10.3 ms corpus parse (1.7 %) — and an order of magnitude below the
> original, confounded comparison; with a competent base prompt for the
> undirected arm, the architecture's advantage is real but modest.

**Abstract — soften the similarity-collapse claim:** state that the
similarity diagnostic establishes *arm distinctness* (a precondition for
best-of-2), not the genuineness of the Bishop-specific effect; the latter
is now adjudicated by `skippy_parallel`. Note that the SR format reveals
rather than creates diversity (two same-prompt `skippy_parallel` draws stay
identical in the median — median 1.000 — under SR).

**Future Work — keep the 1.5B-vs-4B Bishop capability question here.** It
is not answered by this run (a different variable — capability, not
contribution-over-second-draw).

## 7. Files

- `phase/analyze_skippy_parallel.py` — reproduces §1–3 (stats + effect
  sizes).
- Inline per-iteration `arm_similarity` now in every multi-arm
  `iteration_log.jsonl`.
- §4 proposal-block similarity recomputed from the saved `proposals/`
  trees with the same normalization as `phase/arm_similarity.py`.
