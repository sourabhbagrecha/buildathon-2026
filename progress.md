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
- [ ] Reconstruct from checkpoint in fresh session
- [ ] Run graph impact analysis before editing
- [ ] Implement + test curveball requirement
- [ ] Final checkpoint

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
