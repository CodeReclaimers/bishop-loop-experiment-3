# Bishop Loop Experiment 3 — project conventions

## Progress logs go to refstore, not files

This project records session/progress notes via refstore, overriding the
file-based default in `~/.claude/CLAUDE.shared.md`.

- **Tool:** `mcp__refstore__write_session_note`
- **Project key:** `bishop_loop_experiment_3`
- **Cadence and content:** same as the shared rule — write a note for
  every commit (or significant change on projects where per-commit
  recording is disabled), structured as Summary / Files modified /
  Decisions / Verbatim verification evidence / What was intentionally
  NOT done / Next steps. Include exact numeric values, command output,
  and the rationale behind rejected alternatives.
- **Do not** create new `progress-YYYYMMDD.md` files or append to
  existing ones in the repo root. The pre-migration file
  `progress-20260524.md` remains for historical continuity but is no
  longer the active log destination.

## Repository layout (load-bearing context for paper edits)

- `paper/paper.md` — the active paper draft.
- `phase/results/<condition>_<seed>/` — per-run experimental artifacts
  (`summary.json`, `iteration_log.jsonl`, `proposals/`, `diffs/`).
  Versioned suffixes (`.partial-…`, `.gamed-…`, `.cpu-only-…`,
  `.nemotron-v1`, `.diff-patch`, etc.) preserve aborted or pilot runs.
- `final_writeup.md`, `summary_report.md`, `final_writeup_data.json`,
  `arm_similarity.json` — consolidated source material for the paper.
  Treat these as authoritative when resolving numeric claims.
