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
[3] ripple.yaml mapping     -> entry point -> Databricks job + output tables (CONFIGURED, explicit)
[4] intent lookup           -> Entire checkpoints / intent notes for the affected pipeline
[5] execute both versions   -> same input snapshot (Delta table on Databricks)
[6] compare on Databricks   -> row-level diff + aggregate diff via SQL warehouse
[7] review card             -> requirement, source locations, affected data products, reproducible comparison
```

MVP scope (deliberately small): one Python pipeline (`pipeline/transactions.py`), three Delta tables (`raw_transactions`, `clean_transactions`, `daily_revenue`), one aggregate (daily net revenue), one seeded regression (`abs(amount)` introduced while "normalizing transaction amounts").

Explicit design choices:
- Source-to-job mapping is **configured** in `ripple.yaml` and labelled as such; automatic discovery is out of scope.
- Graph-derived relationships are labelled separately from configured mappings.
- Databricks is used for the input snapshot (Delta), for storing both outputs, and for computing the row-level and aggregate comparison via SQL. A local execution fallback with cached evidence exists for demo resilience.

## Entire Graph findings and verification
Recorded evidence lives in `evidence/graph/` (raw JSON) and is re-run live by `ripple review`.

- **Graph search** (`entire graph search --query "normalize transaction amounts refunds negative"`): top hit `normalize_amount` in `pipeline/transactions.py:13`, signals include `graph:callers`. Evidence: `evidence/graph/search_normalize_amount.txt`.
- **Impact analysis before the seeded change** (`entire graph impact --symbol normalize_amount`): callers `clean_transactions` (depth 1, call site line 40) and `run` (depth 2, via `clean_transactions`, call site line 62); `completeness_level: ok`, no partial failures. Evidence: `evidence/graph/impact_normalize_amount.json`. Verified against source: the call sites exist at the reported lines, and `tests/test_graph.py` asserts the parsed relationships.
- **Semantic diff** of the seeded regression (`entire graph diff --base main --head demo/abs-normalize --json`): one `body_changed` function, `normalize_amount`, dependents 1. Evidence: `evidence/graph/diff_main_vs_demo.json`. Verified at runtime: executing base and head over the same snapshot changes 33 of 150 `clean_transactions` rows (exactly the refund rows) and 13 of 14 `daily_revenue` rows.
- Graph relationships on the review card are labelled `[CALLS, entire-graph]`; configured mappings are labelled `source = configured`. The graph's own `warnings` and `completeness` fields are passed through onto the card.
- Final semantic diff of the submitted implementation: to be recorded at checkpoint 4.

## Noon Curveball: what changed and how we adapted
Curveball received (Track 2, "Graph is evidence, not an oracle"): the product must not present incomplete graph relationships as certain, must identify partial analysis, must provide a safe fallback or verification path, must keep working for fully resolved code, and must ship a test/fixture representing incomplete analysis (dynamic dispatch, generated code, reflection).

Response to be recorded after the fresh session implements it.

## Checkpoint links and what each checkpoint proves
1. Initial understanding and intended architecture: this commit.
2. Last stable state before the Curveball: the commit "Ripple MVP" (checkpoint 2, see progress.md for the id). Proves an end-to-end workflow: graph diff -> impact -> configured mapping -> intent -> execute both versions -> Databricks comparison -> review card, with 15 passing tests.
3. Response to the Curveball: to be added.
4. Final implementation and verification: to be added.

## Setup, run and test instructions
Requirements: Python 3.11+ (stdlib only, no pip dependencies), `entire` CLI with the graph plugin, `git`. For the Databricks backend: `databricks` CLI authenticated to the demo workspace (profile `DEFAULT`; no secrets in this repo).

```bash
# tests (15 tests: intent, seeded regression, graph parsing, card, SQL generation)
python3 -m unittest discover -s tests -v

# review the seeded regression locally (exit code 1 = BLOCK, 0 = PASS)
python3 -m ripple review --base main --head demo/abs-normalize

# same, with the comparison executed on Databricks and the card written to evidence/
python3 -m ripple review --base main --head demo/abs-normalize --backend databricks --out evidence/review_card_demo.md

# control case: nothing changed -> PASS
python3 -m ripple review --base main --head main
```

`demo/abs-normalize` is the branch holding the seeded regression (`abs()` introduced in `normalize_amount`). The review card for it is checked in at `evidence/review_card_demo.md` (+ `.json`) as the fallback demo asset.

## Databricks use, data sources and limitations (if applicable)
Opting in to Best Use of Databricks.

- **Capabilities used:** Unity Catalog Delta tables (`workspace.ripple.raw_transactions`, `workspace.ripple.clean_transactions`, `workspace.ripple.daily_revenue`) and the serverless SQL warehouse (`c9a0bd38022ced72`) through the SQL Statement Execution API. Code: `ripple/databricks_backend.py`.
- **Why essential:** the comparison that decides BLOCK vs PASS is computed as SQL on Databricks over both versions of the outputs, tagged with a `run_id`, so a reviewer can re-query the exact rows (`SELECT ... WHERE run_id = '...'`). The statement ids and SQL are printed on the card and saved to `evidence/databricks/last_run.json`.
- **Execution model (honest scope):** the two Python versions are executed locally from git revisions over the snapshot; their outputs and the input snapshot are written to Delta, and the row-level and aggregate diff plus totals are computed on Databricks. Running the Python itself as a Databricks job is the next step (`databricks_job` in `ripple.toml` is a placeholder name).
- **Data provenance:** `data/raw_transactions.csv` is SYNTHETIC (seed 2026, 150 rows, `data/generate_snapshot.py`). No real or personal data.
- **Fallback:** if the CLI or warehouse fails, the card falls back to the local comparison, says so in Notes, and points at the cached evidence file.
- **Limitations:** Free Edition single 2X-Small warehouse (cold start about 1 minute); inserts use literal `VALUES` (fine for 150 rows, not for millions); no Unity Catalog lineage yet, data products are configured in `ripple.toml`.

## Known limitations and next steps
To be added.
