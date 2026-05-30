# Research-integrity post-mortem: the unreproducible similarity numbers

**Date:** 2026-05-30 · **Status:** resolved · **Severity:** low (caught before
publication; scientific conclusion unaffected) · **Class:** AI-assisted research
integrity / reproducibility.

## 1. Summary

While preparing the v1.1.0 release of the *Bishop-Loop* paper, a verification
pass found that the arm-to-arm proposal-similarity statistics in
`phase/RESULTS_skippy_parallel.md` §4 were **not reproducible**. The numbers had
been produced by an uncommitted, one-off analysis script in a prior agentic
session; the resulting table silently mixed two different `difflib` granularities
within single rows, so no single computation reproduces it. The figures had
propagated into the committed results memo and into an uncommitted draft of the
paper's new §5.4. They were corrected before the paper was committed or released.
The published v1.1.0 paper uses corrected, reproducible numbers, and the
qualitative conclusion never changed.

## 2. Timeline

- **2026-05-29** — An agentic session (`claude-code-via-gamma-mcp`) completed the
  pre-registered 70-run `skippy_parallel` sweep, ran the stats, and wrote
  `phase/RESULTS_skippy_parallel.md` (committed `48c2c54af`). The committed
  `phase/analyze_skippy_parallel.py` reproduces the *final-metric* statistics —
  but it contains no similarity code. The proposal-block similarity numbers came
  from a separate computation. That session's own log records it: *"the
  proposal-block recompute was a one-off in-session script."* The script was
  never committed.
- **2026-05-30 (integration)** — In a later session, the memo's similarity
  numbers were transcribed into a new §5.4 of the paper (working tree only). At
  that point the transcription was explicitly flagged as "not independently
  re-derived," with an offer to verify.
- **2026-05-30 (detection)** — The user asked to "rerun the similarity numbers
  just to be sure." Re-running the documented method produced different numbers;
  a sweep of ~12 extraction/granularity variants showed the original row was
  internally inconsistent and reproducible by no single method.
- **2026-05-30 (correction)** — §5.4 was switched to a single documented method
  (all-blocks, character-level), reproduced by a newly committed script,
  `phase/verify_skippy_parallel_similarity.py`. The corrected paper was then
  committed (`426b5748d`) and released as v1.1.0. The erroneous figures never
  reached a committed or released *paper*.
- **2026-05-30 (remediation)** — This post-mortem written; the stale table in
  `phase/RESULTS_skippy_parallel.md` §4 corrected with a visible correction note.

## 3. What was wrong (the technical defect)

The memo reported, for each condition, a row of {mean, median, %≥0.95, %≤0.30,
%≤0.10}. Re-running on the full data (n = 6,054 and 7,521 pairs; all pairs, not a
sample) shows the row is an interleaving of **two** `difflib` granularities —
character-level and line-level — and the interleaving is the same in both rows:

| statistic | memo value | char-level | line-level | row's column came from |
|---|--:|--:|--:|---|
| bishop median | **0.139** | 0.222 | 0.141 | **line** |
| bishop mean | **0.360** | 0.410 | 0.355 | **line** |
| bishop %≤0.30 | **64.6** | 61.5 | 65.8 | **line** |
| bishop %≥0.95 | **9.7** | 9.85 | 6.73 | **char** |
| skippy_parallel %≥0.95 | **92.4** | 92.50 | 87.18 | **char** |
| skippy_parallel %≤0.10 | **4.1** | 0.10 | 3.83 | **line** |

The `%≥0.95` column is unmistakably character-level (92.4 vs 92.50; 9.7 vs 9.85).
Every other column is unmistakably line-level (bishop median 0.139 vs the
line-level 0.141, not the char-level 0.222). The two granularities differ because
`difflib.SequenceMatcher(None, a, b)` operates on whatever sequence it is handed —
a *string* (character-level) or a *list of lines* (line-level) — and the one-off
script evidently produced both and tabulated columns from each. One additional
cell — bishop `%≤0.10 = 28.8` — matches *no* method computed here (line-level
gives 21.85), suggesting it was a third pass or a hand-estimate when the table was
widened for the memo.

A compounding error: the memo described the method as *"the same methodology as
`phase/arm_similarity.py`"* — which is character-level, first-block extraction.
The actual numbers are predominantly line-level. The documented method does not
reproduce the documented numbers.

## 4. Root causes

1. **Ephemeral analysis code.** The script that produced the numbers was never
   committed — irreproducible by construction. The committed `analyze_*` script
   covers only the final-metric stats, not similarity.
2. **A granularity bug.** Character-level vs. line-level `difflib` were mixed
   within one summary table, almost certainly across edits/cells of the one-off
   script, with no check that all columns came from one array.
3. **Documentation from memory, not code.** The stated method ("same as
   `arm_similarity.py`") did not match what was actually run.
4. **No reproduction gate.** Nothing required the numbers to be regenerated from
   committed code before they entered a results memo and a paper draft.
5. **Detection was discretionary.** The error surfaced only because a human asked
   for a re-verification. There was no automated or procedural backstop.

## 5. Detection, impact, and the part that held

**Near-miss, not a hit.** The figures reached a committed *memo* (`48c2c54af`) and
an uncommitted paper draft, then were caught one human-initiated verification step
before the paper was committed and assigned a DOI. The released v1.1.0 paper
(Zenodo `10.5281/zenodo.20465967`) contains corrected, reproducible numbers.

**The conclusion never depended on the bad figures.** Across every method tried,
the *sign and rough magnitude* were stable: two undirected same-model draws are
byte-identical in the median (median similarity 1.000); Bishop-directed arms are
genuinely distinct (~57–66% of iterations ≤ 0.30 similar). The architecture
finding rests on the final-metric statistics, which were independently
reproduced from a committed script (`phase/analyze_skippy_parallel.py`) and were
correct throughout. So the integrity of the *result* was never in question — only
the precision and reproducibility of a supporting diagnostic.

This is also why the error was easy to miss without re-running: the numbers were
*plausible*. They had the right sign, a believable magnitude, and a
headline-friendly "92%." Surface plausibility is exactly what lets a wrong number
pass casual review.

## 6. Why it's worth recording anyway

The failure mode generalizes beyond this paper, and it is becoming more common as
agentic AI does more of the analysis in research workflows:

- **Confident, plausible, wrong.** An agent can emit quantitative claims that look
  right (correct sign/scale, clean round numbers) but are the product of a buggy
  or conflated computation.
- **Irreproducible by construction.** When the generating computation is a
  throwaway script, the error cannot be re-derived later — there is nothing to
  diff against. "Reproducible" has to mean *a committed script regenerates the
  figure*, not "someone computed it once."
- **Documentation drift.** A method described from memory rather than from the
  code can silently diverge from what was run, defeating the reader's ability to
  reproduce it.
- **Headline numbers get less scrutiny.** The most quotable figure ("92%") is the
  one most likely to be copied forward unchecked.

None of this is catastrophic, and none of it required novel safeguards to catch —
ordinary reproducibility discipline did. That is the reassuring part and the
lesson at once.

## 7. Remediation

**Done**
- §5.4 of the paper uses one documented method (all-blocks, character-level),
  reproduced by the committed `phase/verify_skippy_parallel_similarity.py`
  (v1.1.0, commit `426b5748d`).
- `phase/RESULTS_skippy_parallel.md` §4 corrected with a visible correction note
  recording the superseded values and the defect (this session).
- This post-mortem written.

**Preventive controls (recommended going forward)**
1. **Commit the script that produces any number destined for a paper.** No
   ephemeral stats. If a figure can't be regenerated by `python <committed file>`,
   it isn't a result yet.
2. **Cite the producing script next to the number** (the paper now does this for
   §5.4).
3. **A pre-publication reproduction gate:** before a number is transcribed into a
   manuscript, regenerate it from committed code and diff against the source.
4. **Document methods from the code, not from memory** — copy the actual call,
   not a recollection of it.
5. **Give headline numbers *more* scrutiny, not less.**

## Appendix — reproduction

Corrected metric (all fenced SR blocks per response, character-level `difflib`
ratio, normalization per `phase/arm_similarity.py`):

```
$ python3 phase/verify_skippy_parallel_similarity.py
skippy_parallel  skippy_a vs skippy_b   n=6054  mean 0.843  median 1.000  61.1% ≥0.95   9.4% ≤0.30   8.4% ≤0.10
bishop           skippy vs bishop_bare  n=7521  mean 0.348  median 0.231   1.8% ≥0.95  56.5% ≤0.30  23.5% ≤0.10
```

Granularity diagnosis (full data, first-block extraction, char vs line):

```
BISHOP (n=7521)          mean    median  %≥.95   %≤.30   %≤.10
  first_block/char       0.4098  0.2224   9.85   61.51    4.06
  first_block/line       0.3552  0.1412   6.73   65.79   21.85
  memo (target)          0.360   0.139    9.7    64.6    28.8     <- median←line, %≥.95←char

SKIPPY_PARALLEL (n=6054) mean    median  %≥.95   %≤.30   %≤.10
  first_block/char       0.9543  1.0000  92.50    4.51    0.10
  first_block/line       0.9451  1.0000  87.18    4.56    3.83
  memo (target)          0.949   1.000   92.4     4.6     4.1      <- %≥.95←char, %≤.10←line
```

Provenance: no committed script ever computed these numbers (verified by
`git log --all -S`, all-blob grep, deleted-file and reflog/stash search). The
generating computation is described by its own author session as "a one-off
in-session script" (2026-05-29 session note, commit `48c2c54af`).
