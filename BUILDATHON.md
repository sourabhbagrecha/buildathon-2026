# Ripple

## One-sentence summary
Ripple connects a code change to its downstream data consequences by combining Entire Checkpoint intent, Entire Graph code relationships, and a Databricks-executed comparison of the old and new transformation over the same input snapshot.

## Problem, intended user and why it matters
A data engineer (or a coding agent) edits a small helper in a transformation pipeline. The diff looks harmless, tests pass, but a downstream report silently changes meaning (for example, refunds stop being negative and revenue is overstated). Git shows *what* changed. Nothing shows *which data products* changed meaning, *by how much*, and *whether that contradicts the original intent*. Ripple answers those three questions in one review card so the reviewer can block or approve with evidence instead of guesswork.

## Selected Entire track and why Entire is essential
**Track 2: Build with Graph Intelligence.**

- **Entire Graph** identifies the changed symbol (`entire graph diff`), its callers and data flows (`entire graph impact`), and therefore which pipeline entry points and data products are reachable from the change. Without the graph, Ripple would have to re-run every pipeline on every change.
- **Entire Checkpoints** carry the *intent* behind the pipeline ("refunds must remain negative"). Ripple reads that intent and puts it next to the measured consequence so the reviewer sees requirement, code location and data evidence together.
- Graph output is treated as evidence, not an oracle: every relationship shown on the review card is labelled with its confidence and can be verified against source lines, tests, and the executed comparison.

## Architecture and main workflow
Planned at checkpoint 1 (initial understanding, written before any implementation):

```
git base..head
   |
   v
[1] entire graph diff       -> changed symbols (e.g. normalize_amount)
[2] entire graph impact     -> callers / data flows -> pipeline entry points
[3] ripple.toml mapping     -> entry point -> Databricks job + output tables (CONFIGURED, explicit)
[4] intent lookup           -> Entire checkpoints / intent notes for the affected pipeline
[5] execute both versions   -> same input snapshot (Delta table on Databricks)
[6] compare on Databricks   -> row-level diff + aggregate diff via SQL warehouse
[7] review card             -> requirement, source locations, affected data products, reproducible comparison
```

MVP scope (deliberately small): one Python pipeline (`pipeline/transactions.py`), three Delta tables (`raw_transactions`, `clean_transactions`, `daily_revenue`), one aggregate (daily net revenue), one seeded regression (`abs(amount)` introduced while "normalizing transaction amounts").

Explicit design choices:
- Source-to-job mapping is **configured** in `ripple.toml` and labelled as such; automatic discovery is out of scope for the MVP (Unity Catalog lineage was added afterwards as a separately labelled, observed source; see "After the Curveball").
- Graph-derived relationships are labelled separately from configured mappings.
- Databricks is used for the input snapshot (Delta), for storing both outputs, and for computing the row-level and aggregate comparison via SQL. A local execution fallback with cached evidence exists for demo resilience.

## Entire Graph findings and verification
Recorded evidence lives in `evidence/graph/` (raw JSON) and is re-run live by `ripple review`.

- **Graph search** (`entire graph search --query "normalize transaction amounts refunds negative"`): top hit `normalize_amount` in `pipeline/transactions.py:13`, signals include `graph:callers`. Evidence: `evidence/graph/search_normalize_amount.txt`.
- **Impact analysis before the seeded change** (`entire graph impact --symbol normalize_amount`): callers `clean_transactions` (depth 1, call site line 40) and `run` (depth 2, via `clean_transactions`, call site line 62); `completeness_level: ok`, no partial failures. Evidence: `evidence/graph/impact_normalize_amount.json`. Verified against source: the call sites exist at the reported lines, and `tests/test_graph.py` asserts the parsed relationships.
- **Semantic diff** of the seeded regression (`entire graph diff --base main --head demo/abs-normalize --json`): one `body_changed` function, `normalize_amount`, dependents 1. Evidence: `evidence/graph/diff_main_vs_demo.json`. Verified at runtime: executing base and head over the same snapshot changes 33 of 150 `clean_transactions` rows (exactly the refund rows) and 13 of 14 `daily_revenue` rows.
- Graph relationships on the review card are labelled `[CALLS, entire-graph]` plus a tri-state evidence label (`confirmed` / `heuristic` / `needs-verification`, see Curveball); configured mappings are labelled `source = configured`. The graph's own `warnings`, `partial_failures` and `completeness` fields are passed through onto the card.
- **Impact analysis before the Curveball edit** (session B, before touching any file): `entire graph impact` on `parse_impact` (4 callers: `graph_impact`, two tests, `review` transitively), `reachable_entry_points` (`review`, two tests, `main`), `decide` (only the two tests) and `review` (`main`, `__main__`). Observation: the graph did not list `review` as a caller of `decide`, although `ripple/cli.py` calls it as `cardmod.decide(rc)` through a module alias. A real, first-hand example of the graph being evidence rather than an oracle; recorded here and handled by the same labels.
- **Dynamic dispatch is a silent miss.** `entire graph impact --symbol normalize_amount --file tests/fixtures/transactions_dynamic_dispatch.py` returns `callers.total = 0`, `completeness_level = ok`, no partial failures and only the benign `W_WORKTREE_SNAPSHOT` warning, although `run` reaches `normalize_amount` through a string registry and `globals()`. Evidence: `evidence/graph/impact_normalize_amount_dynamic.json` (raw output, also the test fixture `tests/fixtures/graph_impact_dynamic.json`). The graph does not know it missed anything, so completeness fields alone cannot flag it.
- Final semantic diff of the submitted implementation: `evidence/graph/diff_checkpoint2_vs_final.json` (see checkpoint 4).

## Noon Curveball: what changed and how we adapted
Curveball received (Track 2, "Graph is evidence, not an oracle"): the product must not present incomplete graph relationships as certain, must identify partial analysis, must provide a safe fallback or verification path, must keep working for fully resolved code, and must ship a test/fixture representing incomplete analysis (dynamic dispatch, generated code, reflection).

Response (fresh session B, reconstructed from checkpoint `01M1TY0G8KHGFN783A6VVB00QR` with `entire checkpoint explain`, then `entire graph impact` on every consumer of graph evidence before editing):

**Assumption invalidated.** The MVP treated every `entire graph impact` caller edge as a certain path to the entry point, and "no configured entry point reached" read as safe. With dynamic dispatch the graph reports zero callers *and* `completeness_level: ok`, so the MVP would have returned PASS without executing anything.

**What changed (smallest complete revision):**
1. **Tri-state evidence labels** on every relationship (`ripple/graph.py: label_caller`): `confirmed` = structural `CALLS` edge with a recorded call site; `heuristic` = non-structural relation (`DATA_FLOWS`, co-change, sibling) or a call edge reported while the graph itself says the run is partial (`completeness_level != ok`, `partial_failures`, or a non-benign warning); `needs-verification` = an edge with no call site, or a path found by Ripple's own scan that the graph cannot see. Labels travel with the `Caller` object into `reachable_entry_points` and onto the card.
2. **Partial-analysis detection from two sources**: the graph's own signals (`graph_partial_reasons`) and a Ripple-side AST scan of the changed file and configured entry files (`scan_dynamic_references`). The scan flags a symbol only when its name appears as a string constant *and* the same file uses reflection (`getattr`, `globals()`, `vars()`, `importlib`, `__import__`, `eval`, `exec`, `sys.modules`); docstrings and comments are ignored, dict keys that merely share a function name are not enough, and a file that does not parse falls back to a regex scan. A failed impact query also counts as partial.
3. **Partial-analysis banner** at the top of the card listing every reason with file:line, an evidence summary line (`N confirmed, N heuristic, N needs-verification`), per-edge labels with the reason, and an explicit "graph reports no callers **but analysis is partial: absence of callers is not evidence of safety**" line.
4. **Safe fallback = execute anyway** (`ripple/cli.py: select_mappings`): when analysis is partial and code changed, every configured entry point the graph did not reach is executed over the snapshot and compared; the card marks it `[fallback (graph did not reach it)]`. Execute-and-compare is the verification path.
5. **Verdict rules** (`ripple/card.py: decide`): BLOCK if outputs differ; PASS only when execution proved outputs identical, or when analysis is complete and every relation is confirmed; a new `NEEDS-VERIFICATION` verdict (exit code 3) when analysis is partial and nothing was executed. PASS on graph evidence alone is impossible in the partial state.
6. **Fixtures and tests**: `tests/fixtures/transactions_dynamic_dispatch.py` (behaviour-identical pipeline routed through `STEP_REGISTRY` + `globals()`), `tests/fixtures/graph_impact_dynamic.json` (real graph output: 0 callers, completeness ok), `tests/fixtures/graph_impact_degraded.json` (graph-reported partial run with a `DATA_FLOWS` edge), `tests/test_curveball.py` (22 tests: labels, scan precision, partial detection, fallback selection, verdicts, card rendering, fixture execution equivalence). The original 15 tests pass unchanged: fully resolved code still gets `confirmed` on every edge, no banner, and the same BLOCK/PASS.
7. Housekeeping the Curveball exposed: only code entities (function/method/class in a code language) are impact-analysed; Markdown sections and JSON keys from `entire graph diff` are counted on the card but not scanned. The `demo/abs-normalize` branch was rebased onto `main` so its diff is the one seeded change again.

**Live demonstration** (branches `demo/dynamic-dispatch`, `demo/dynamic-dispatch-abs`, `demo/dynamic-dispatch-safe`; the graph indexes the checked-out tree, so run from a worktree with the dynamic branch checked out):
- `demo/dynamic-dispatch..demo/dynamic-dispatch-abs`: graph reaches no entry point; Ripple flags partial (registry line 13, `globals()` line 26), executes `pipeline.transactions:run` as fallback, finds 33/150 rows and 13/14 days changed, verdict BLOCK. Databricks comparison ran on the same run: net revenue 13854.10 -> 18033.82. Card: `evidence/review_card_dynamic.md` (+ `.json`), Databricks evidence `evidence/databricks/dynamic_run.json`.
- `demo/dynamic-dispatch..demo/dynamic-dispatch-safe` (behaviour-preserving refactor): same partial banner, fallback execution, 0 rows changed, verdict "PASS ... (verified by execution; graph analysis partial, see banner)". Card: `evidence/review_card_dynamic_safe.md`.
- `main..demo/abs-normalize` (static calls): 4 `confirmed` edges, no banner, BLOCK as before.

## After the Curveball: the remaining items (checkpoint 5)
The "next steps" recorded at checkpoint 4 were all implemented in a follow-up session, plus a repository repair:

1. **Repository repair.** PRs #2, #3 and #4 merged the three `demo/*` branches into `main` on GitHub. That put a conflict-mangled, syntactically invalid `pipeline/transactions.py` on `main` (an unterminated docstring after the merged `abs()` and dynamic-dispatch variants), and it erased the demo baseline (`main..demo/abs-normalize` would be empty). `main`'s pipeline file is restored to the static, intent-respecting version; the demo branches stay separate and keep diffing against `main`.
2. **Automatic worktree at `head`** (`ripple/worktree.py`). `entire graph` indexes the working tree, so impact and the dynamic-reference scan used to describe whatever was checked out. `ripple review` now materialises `--head` in a temporary detached worktree (unless the checkout already is head or `--no-worktree` is given), points the graph and the scans at it, and removes it afterwards. The card says which tree was analysed. The dynamic-dispatch demo therefore runs from the main checkout without any manual `git worktree add`.
3. **Cross-file dynamic-reference scan** (`ripple/graph.py: scan_set`, `scan_cross_file_references`). The scan set is the changed Python files, the configured entry files, every Python and config file (`.yaml/.yml/.toml/.json/.ini/.cfg`) in their directories, plus `[scan] config_files` / `extra_dirs` from `ripple.toml`. A changed symbol whose name appears as data in file A (a string constant in Python, a bare token in a config file, comments excluded) while a *different* Python file B in the set dispatches by reflection is reported as `needs-verification` with both locations ("cross-file: name appears as data here; `runner.py:7` dispatches via importlib"). Fixture: `tests/fixtures/cross_file/` (`steps.yaml` registry + `runner.py` with `importlib`/`getattr`). The static repo still yields no cross-file reference, so fully resolved code is unaffected.
4. **CONFIGURES-edge check** (`configures_references`). If the graph reports a `CONFIGURES` relation (a data file naming the symbol; the graph supports it for TOML/YAML/JSON), the edge is labelled `heuristic` and the analysis is marked partial, because data-driven dispatch may follow.
5. **Pipeline executed as a Databricks job** (`ripple/databricks_job.py`, `--execute databricks`). Ripple generates a self-contained script embedding the base and head sources, uploads it as a workspace file under `/Workspace/Users/<me>/ripple/`, and submits a one-time **serverless** run (`spark_python_task`, `environments.spec.client = 4`). The job reads the published snapshot rows from `workspace.ripple.raw_transactions` for the `run_id`, executes both versions inside Databricks, and writes `clean_transactions` / `daily_revenue` with `version = base|head` through Spark. The SQL comparison then runs as before. The card shows the run id, URL, state and duration, and the script is kept under `evidence/databricks/jobs/`. If the job fails, the locally executed outputs are published instead and the card says so. `--execute local` (default) keeps the previous behaviour.
6. **Unity Catalog lineage** (`discover_lineage`, `--no-lineage` to skip). With the Databricks backend, Ripple queries `system.access.table_lineage` for the configured input and output tables (last 30 days) and adds a lineage block to section 3: upstream tables, downstream tables, named readers (jobs, notebooks, dashboards) and table-to-table flows, labelled `source = unity-catalog-lineage` and **observed** (lineage is recorded when a query actually ran, so it is evidence of a real consumer). Configured mappings remain the explicit contract; lineage never replaces them, and absence of lineage is stated not to be evidence of no consumers. Because the job path writes through Spark, lineage `raw_transactions -> clean_transactions / daily_revenue` is recorded for job runs.
7. **Execution failures are findings.** A base or head revision that fails to import or run (as the mangled `main` did) no longer crashes the review: the error is on the card and the verdict is `NEEDS-VERIFICATION` when no comparison could be made.
8. Tests: `tests/test_next.py` (19 tests: cross-file scan precision, scan set, CONFIGURES, worktree lifecycle on a temporary git repo, job script and request shape, lineage parsing and rendering, execution errors). 56 tests pass.

## Checkpoint links and what each checkpoint proves
1. Initial understanding and intended architecture: this commit.
2. Last stable state before the Curveball: commit 97e3307, Entire checkpoint `01M1TY0G8KHGFN783A6VVB00QR`. Proves an end-to-end workflow: graph diff -> impact -> configured mapping -> intent -> execute both versions -> Databricks comparison -> review card, with 15 passing tests.
3. Response to the Curveball: commit 8cf3d61, Entire checkpoint `01M1TYWW6PB644YRN2KZXMKCP3`. Proves: tri-state labels, partial-analysis banner, execute-anyway fallback, NEEDS-VERIFICATION verdict, dynamic-dispatch fixture with real graph output, 37 passing tests, live dynamic-dispatch demo cards.
4. Final implementation and verification: commit 3f24ec9, Entire checkpoint `01M1TYYB3Y2QA3NY7Y5FXFQFM4`, with the final semantic diff `entire graph diff --base 97e3307 --head 8cf3d61` saved as `evidence/graph/diff_checkpoint2_vs_final.json` (57 Python entity changes: 8 added + 7 changed in `ripple/graph.py`, 3 in `ripple/cli.py`, 4 in `ripple/card.py`, the rest fixture and tests).
5. Remaining items (repository repair + the four next steps): commit b8fcc03 on branch `ripple-next`, Entire checkpoint `01M1V124D75T56BXPP096FYZF6`. Semantic diff `entire graph diff --base 281ad72 --head b8fcc03` saved as `evidence/graph/diff_checkpoint4_vs_next.json` (208 entity changes across 18 files; product code: `ripple/worktree.py` 5 added, `ripple/databricks_job.py` 7 added, `ripple/graph.py` 6 added + 4 changed, `ripple/databricks_backend.py` 4 added + 1 changed, `ripple/config.py` 1 added + 2 changed, `ripple/cli.py` and `ripple/card.py` changed). The graph itself flags `E_PARSE_ERROR` on the base side of `pipeline/transactions.py`, which is the broken `main` file this checkpoint restores. Proves: live Databricks job execution (run 43140873411386), lineage lookup, worktree-based analysis of the dynamic branches from the main checkout, 56 passing tests.

## Setup, run and test instructions
Requirements: Python 3.11+ (stdlib only, no pip dependencies), `entire` CLI with the graph plugin, `git`. For the Databricks backend: `databricks` CLI authenticated to the demo workspace (profile `DEFAULT`; no secrets in this repo).

```bash
# tests (37 tests: intent, seeded regression, graph parsing, card, SQL generation, Curveball)
python3 -m unittest discover -s tests -v

# review the seeded regression locally (exit code 1 = BLOCK, 0 = PASS)
python3 -m ripple review --base main --head demo/abs-normalize

# same, with the comparison executed on Databricks and the card written to evidence/
python3 -m ripple review --base main --head demo/abs-normalize --backend databricks --out evidence/review_card_demo.md

# control case: nothing changed -> PASS
python3 -m ripple review --base main --head main

# Curveball demo: dynamic-dispatch pipeline. Ripple materialises --head in a temporary
# worktree automatically, so this runs from the main checkout.
python3 -m ripple review --base demo/dynamic-dispatch --head demo/dynamic-dispatch-abs   # BLOCK, partial banner, fallback
python3 -m ripple review --base demo/dynamic-dispatch --head demo/dynamic-dispatch-safe  # PASS verified by execution

# execute both versions AS A DATABRICKS JOB (serverless), compare on Databricks, add Unity Catalog lineage
python3 -m ripple review --base main --head demo/abs-normalize --execute databricks --out evidence/review_card_demo_databricks_job.md
```

Flags: `--execute local|databricks` (where the two versions run), `--backend local|databricks` (where the comparison is computed), `--no-worktree`, `--no-lineage`, `--no-entire-checkpoint`.

Exit codes: 0 PASS, 1 BLOCK, 3 NEEDS-VERIFICATION (partial analysis and nothing executed, or execution failed), 2 graph error.

`demo/abs-normalize` is the branch holding the seeded regression (`abs()` introduced in `normalize_amount`). The review card for it is checked in at `evidence/review_card_demo.md` (+ `.json`) as the fallback demo asset.

## Databricks use, data sources and limitations (if applicable)
Opting in to Best Use of Databricks.

- **Capabilities used:** Unity Catalog Delta tables (`workspace.ripple.raw_transactions`, `workspace.ripple.clean_transactions`, `workspace.ripple.daily_revenue`) and the serverless SQL warehouse (`c9a0bd38022ced72`) through the SQL Statement Execution API. Code: `ripple/databricks_backend.py`.
- **Why essential:** the comparison that decides BLOCK vs PASS is computed as SQL on Databricks over both versions of the outputs, tagged with a `run_id`, so a reviewer can re-query the exact rows (`SELECT ... WHERE run_id = '...'`). The statement ids and SQL are printed on the card and saved to `evidence/databricks/last_run.json`.
- **Execution model:** with `--execute databricks` the two Python versions run inside a serverless Databricks job (one-time run, `spark_python_task` on a generated workspace file) over the Delta snapshot, and write both outputs through Spark; with the default `--execute local` they run locally from git revisions and only the outputs are uploaded. In both cases the row-level and aggregate diff plus totals are computed on Databricks. `databricks_job` in `ripple.toml` is the run name.
- **Lineage:** `system.access.table_lineage` is queried for the configured tables and shown as an observed, separately labelled source next to the configured mappings.
- **Data provenance:** `data/raw_transactions.csv` is SYNTHETIC (seed 2026, 150 rows, `data/generate_snapshot.py`). No real or personal data.
- **Fallback:** if the CLI or warehouse fails, the card falls back to the local comparison, says so in Notes, and points at the cached evidence file.
- **Limitations:** Free Edition single 2X-Small warehouse (cold start about 1 minute); inserts use literal `VALUES` (fine for 150 rows, not for millions); no Unity Catalog lineage yet, data products are configured in `ripple.toml`.

## Known limitations and next steps
- The dynamic-reference scan is Python-only. The cross-file rule needs a reflection site somewhere in the scan set (changed files, entry files, their directories, configured extras); a registry consumed by code outside that set is not caught, and the graph-signal path still applies. Next: a `--scan-dir` sweep of the whole repository behind a flag, and support for other languages via the graph's own string-constant symbols.
- The Databricks job embeds the entry file only; a pipeline spread over several modules would need the package uploaded (wheel or `import-dir`). Inserts of the snapshot still use literal `VALUES` (fine for 150 rows). One-time runs are not saved jobs, so they do not appear under Jobs in the UI (the run URL on the card opens them).
- Lineage is limited to what Unity Catalog has observed in the last 30 days; readers outside Databricks (a BI tool pulling through JDBC) show as entity-less reads. Configured mappings therefore remain the source of record for data products.
- `main` on GitHub still needs the restore PR merged (`ripple-next`); until then `--base main` executes the broken file and the card reports it as an execution error (NEEDS-VERIFICATION) instead of a comparison.
