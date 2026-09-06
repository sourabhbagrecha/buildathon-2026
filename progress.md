# Progress log

Timestamps are IST, 6 September 2026.

## 13:10 Session 1 (initial understanding)
- Repo state: empty git history, Entire enabled (hooks installed), Entire Graph plugin v0.4.0 installed, `init-agents` already run (AGENTS.md / CLAUDE.md present).
- Track chosen: Track 2 (Graph Intelligence). Product: Ripple.
- Databricks Free Edition workspace reachable via CLI profile `DEFAULT`; serverless SQL warehouse available.
- Wrote BUILDATHON.md with intent and intended architecture. No product code yet.
- Next: commit this state so Entire records checkpoint 1 (initial understanding / intended architecture), then start a fresh agent session per the Curveball procedure.

## Curveball procedure status
- [x] Stop implementation (nothing implemented yet)
- [x] Commit last stable version (ab574b4)
- [x] Confirm checkpoint: `entire checkpoint list` confirmed after `entire session attach --force` (the session started before the first commit existed; hook logged `failed to get HEAD: reference not found`, so the commit hook could not link the session). The Entire mirror remote rejects non-fast-forward pushes, so the attach was redone on this follow-up commit instead of amending ab574b4.
- [x] End current agent session, start fresh one (13:30)
- [x] MVP built and committed as checkpoint 2: 97e3307 / `01M1TY0G8KHGFN783A6VVB00QR` (14:10)
- [x] Reconstruct from checkpoint in fresh session B (Curveball) (14:20)
- [x] Run graph impact analysis before editing (`parse_impact`, `reachable_entry_points`, `decide`, `review`)
- [x] Implement + test curveball requirement (checkpoint 3, see below)
- [x] Final checkpoint (checkpoint 4, see below)

## 13:30 Handoff to fresh session A (MVP build)
- Session 1 ends here. A fresh agent builds the Ripple MVP (pipeline, snapshot, seeded regression, graph wrapper, comparison, Databricks backend, review card, tests) and commits it as checkpoint 2 (last stable state before the Curveball response).
- Interpretation of the Curveball procedure given that no code existed at noon: procedural steps (commit, checkpoint, fresh session) done first; the Curveball's technical requirements are implemented by a second fresh session against the MVP so that graph impact analysis has real code to analyse.

## 13:40 Push note (session 1)
- The Entire mirror accepted the first push of `main` (ab574b4) but now rejects further pushes to `main` with `[remote rejected] main -> main (protected branch)`. Non-fast-forward pushes are also refused.
- Workaround: work is pushed to branch `ripple` on the same remote (`git push origin main:ripple`). Checkpoint refs (`refs/entire/checkpoints/*`) sync fine. Submission owner should either lift main protection on GitHub and fast-forward `main`, or submit the `ripple` branch SHA.

## 14:05 Session A resumed (MVP build, this session)
- Found session A had stopped after committing the pipeline, snapshot, `ripple.toml` and graph evidence (6fbdd6b); `ripple/` was empty and there were no tests.
- Built the `ripple` package: `config` (ripple.toml), `graph` (wrappers for `entire graph diff` / `impact`, passes warnings + completeness through), `intent` (INTENT.md + `entire checkpoint search`), `execute` (runs an entry point at a git revision over the snapshot), `compare` (row + aggregate diff), `databricks_backend` (Delta tables in `workspace.ripple`, SQL comparison via Statement Execution API), `card` (markdown/JSON review card, BLOCK/PASS), `cli`.
- Verified: `python3 -m ripple review --base main --head demo/abs-normalize --backend databricks` ran on the live warehouse (about 70 s including cold start); 33/150 rows and 13/14 days differ, total net revenue 13854.10 -> 18033.82. Card + Databricks evidence saved under `evidence/`. Control case `main..main` gives PASS.
- Tests: 15 unittest tests pass (`python3 -m unittest discover -s tests`). Fixtures: resolved graph diff/impact JSON and the abs() regression module.
- Bug fixed on the way: `entire graph diff` returns `"files": null` when nothing changed; parser now tolerates it.
- Decision: kept the pipeline execution local (git revision -> exec) and put storage + comparison on Databricks. Recorded as the honest scope in BUILDATHON.md; Databricks job execution is the next step.
- Next: commit as checkpoint 2 (last stable state before the Curveball response), push to `ripple`, then end this session and start the fresh Curveball session.

## 14:12 Handoff to fresh session B (Curveball response)
- Checkpoint 2 = commit 97e3307, Entire checkpoint `01M1TY0G8KHGFN783A6VVB00QR` (pushed to `origin/ripple`; `main` on the mirror is still protected).
- Session B must, in order: reconstruct from `entire checkpoint explain 01M1TY0G8KHGFN783A6VVB00QR`; run `entire graph impact` on the consumers of graph evidence (`ripple/graph.py`: `parse_diff`, `parse_impact`, `reachable_entry_points`; `ripple/card.py`: `render_markdown`, `decide`; `ripple/cli.py`: `review`) BEFORE editing; then implement the Curveball.
- Assumption the Curveball invalidates: the MVP treats every `entire graph impact` caller edge as a certain path to the entry point, and `decide()` only looks at data diffs. With dynamic dispatch / generated code / reflection the graph can miss a caller, so "no configured entry point reached" would wrongly read as safe.
- Intended revision (smallest complete): tri-state evidence labels on every relationship (`confirmed` structural with call site; `heuristic`/`incomplete` when warnings, partial_failures, completeness != ok, or heuristic relation types; `needs-verification` for claims not backed by a call site); a "partial analysis" banner on the card; a safe fallback that runs the configured entry points anyway (execute-and-compare is the verification path) and never returns PASS on graph evidence alone when analysis is partial; a fixture under `tests/fixtures/` with a dynamic-dispatch pipeline (e.g. `getattr`/registry lookup) plus graph JSON showing incomplete analysis; tests for both resolved and partial cases; existing 15 tests keep passing.

## 14:20 Session B (Curveball response, fresh session)
- Reconstructed from `entire checkpoint explain 01M1TY0G8KHGFN783A6VVB00QR` (27 files, transcript scope) and progress.md; read only the files named in the handoff.
- Impact before editing: `parse_impact` 4 callers (graph_impact, 2 tests, `review` transitive); `reachable_entry_points` 4 callers (`review`, 2 tests, `main`); `decide` 2 callers (tests only; the graph missed `cardmod.decide(rc)` in `ripple/cli.py`, a module-alias call); `review` 2 callers (`main`, `__main__`), 16 callees. Conclusion: adding fields with defaults to `Caller`/`ImpactResult`/`ReviewCard` and an optional parameter to `parse_impact` breaks no caller; `decide` needed new inputs (analysis state), added as card fields.
- Probe before design: wrote the dynamic-dispatch fixture and ran the real `entire graph impact` on it. Result: 0 callers, `completeness_level: ok`, no partial failures. The graph does not signal the miss, so Ripple needs its own dynamic-reference scan in addition to graph signals. Raw output saved as the fixture and under `evidence/graph/`.
- Implemented: tri-state labels (`label_caller`), partial detection (`graph_partial_reasons`, AST-based `scan_dynamic_references`, `analysis_state`), banner + evidence summary + per-edge reasons on the card, `select_mappings` execute-anyway fallback, `NEEDS-VERIFICATION` verdict (exit 3), code-kind filter for impact analysis, 22 new tests in `tests/test_curveball.py`. 37 tests pass.
- Scan precision iterations: first version (string literal alone) flagged dict keys like `"kind"` and JSON keys; second required string + reflection in the same file; final uses the AST so docstrings/comments never count, with a regex fallback for files that do not parse.
- Demo branches: `demo/abs-normalize` rebased onto `main` (it was behind main, so `entire graph diff` reported dozens of removed doc/JSON entities). New `demo/dynamic-dispatch` (pipeline routed through a string registry + `globals()`), `demo/dynamic-dispatch-abs` (seeded abs regression on it), `demo/dynamic-dispatch-safe` (behaviour-preserving refactor).
- Live results (worktree with the dynamic branch checked out, since the graph indexes the working tree): abs -> BLOCK with partial banner and fallback execution, 33/150 rows, 13/14 days, Databricks net revenue 13854.10 -> 18033.82 (`evidence/review_card_dynamic.md`, `evidence/databricks/dynamic_run.json`); safe -> PASS "verified by execution; graph analysis partial" (`evidence/review_card_dynamic_safe.md`); static `main..demo/abs-normalize` -> BLOCK with 4 confirmed edges and no banner.
- Gotcha: committing inside a git worktree while Entire hooks are installed created checkpoint commits and, with `commit -a`, swept the copied `ripple/` into a demo branch once. Fixed by resetting the branch pointers; demo branches now contain only the intended pipeline change.

## 14:26 Checkpoint 3 (Curveball response)
- Commit 8cf3d61, Entire checkpoint `01M1TYWW6PB644YRN2KZXMKCP3`. 37 tests pass. Live cards under `evidence/`.

## 14:30 Checkpoint 4 (final implementation and verification)
- Final semantic diff `entire graph diff --base 97e3307 --head 8cf3d61 --json` saved as `evidence/graph/diff_checkpoint2_vs_final.json`: 57 Python entity changes, no warnings. Product code: `ripple/graph.py` (8 added: `DynamicReference`, `ChangedSymbol.is_code`, `ImpactResult.is_partial`, `graph_partial_reasons`, `label_caller`, `scan_dynamic_references`, `_scan_dynamic_references_regex`, `analysis_state`; `parse_impact` and `graph_impact` signature_changed with optional parameters; `Caller`, `ImpactResult`, `ChangedSymbol`, `parse_diff`, `reachable_entry_points` body_changed), `ripple/cli.py` (`select_mappings` added; `review`, `main` body_changed), `ripple/card.py` (`_evidence_summary` added; `ReviewCard`, `decide`, `render_markdown` body_changed). The rest are the dynamic-dispatch fixture (5 functions) and `tests/test_curveball.py` (22 tests, 5 classes, 3 helpers). Matches the impact analysis done before editing: no caller of `parse_impact` / `reachable_entry_points` / `decide` needed a change beyond `review` itself.
- Verification: `python3 -m unittest discover -s tests` 37/37; `main..demo/abs-normalize` BLOCK with 4 confirmed edges; `main..main` PASS; dynamic-dispatch abs BLOCK (partial banner, fallback, Databricks run `demo/dynamic-dispatch..demo/dynamic-dispatch-abs@20260906T085304Z`); dynamic-dispatch safe PASS verified by execution.
- Checkpoint 4 commit and Entire checkpoint id: see `git log -1` on `ripple` (recorded after this commit lands).
- Push note: the mirror still rejects `main`; work is on branch `ripple`. `demo/abs-normalize` was rebased and needs a force push (`git push --force-with-lease origin demo/abs-normalize`), which this session did not perform.
