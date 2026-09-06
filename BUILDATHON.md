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
To be filled during implementation (graph search, impact analysis before the high-risk change, final semantic diff).

## Noon Curveball: what changed and how we adapted
Curveball received (Track 2, "Graph is evidence, not an oracle"): the product must not present incomplete graph relationships as certain, must identify partial analysis, must provide a safe fallback or verification path, must keep working for fully resolved code, and must ship a test/fixture representing incomplete analysis (dynamic dispatch, generated code, reflection).

Response to be recorded after the fresh session implements it.

## Checkpoint links and what each checkpoint proves
1. Initial understanding and intended architecture: this commit.
2. Last stable state before the Curveball: to be added.
3. Response to the Curveball: to be added.
4. Final implementation and verification: to be added.

## Setup, run and test instructions
To be added.

## Databricks use, data sources and limitations (if applicable)
Opting in to Best Use of Databricks. Data is synthetic (generated transactions), clearly labelled. Details to be added.

## Known limitations and next steps
To be added.
