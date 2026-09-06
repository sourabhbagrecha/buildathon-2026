# Ripple review card: `demo/dynamic-dispatch` -> `demo/dynamic-dispatch-safe`

**Verdict:** PASS: outputs identical for base and head over the snapshot (verified by execution; graph analysis partial, see banner)

> **PARTIAL ANALYSIS.** The call graph may be missing callers of the changed code
> (dynamic dispatch, reflection, generated code, or a degraded graph run).
> Graph relationships below are labelled per edge; nothing here is PASS on graph evidence alone.
> - normalize_amount: dynamic reference to `normalize_amount` at pipeline/transactions.py:13 (symbol name used as a string literal); the graph cannot resolve this path
> - normalize_amount: dynamic reference to `normalize_amount` at pipeline/transactions.py:26 (reflection/dynamic dispatch via globals()); the graph cannot resolve this path
> - Fallback: executed configured entry point(s) `pipeline.transactions:run` even though the graph did not reach them.

**Evidence:** analysis `partial`; graph relations: 2 confirmed, 0 heuristic, 0 needs-verification

## 1. Original requirement (intent)
- Requirement: Refunds must remain negative. `normalize_amount` derives the sign of an amount from the transaction kind: purchases positive, refunds negative. Daily net revenue (`daily_revenue`) is `sum(amount)` per day and is only correct if this holds.
- Source: `pipeline/INTENT.md`, Entire checkpoint `01M1TVFK5MAS7B1JFN41QA2JQ8` (`entire checkpoint explain 01M1TVFK5MAS7B1JFN41QA2JQ8`) [intent-file]

## 2. Source locations (Entire Graph, source = entire-graph)
- Changed function `normalize_amount` in `pipeline/transactions.py:19` (body_changed, graph dependents: 13)
- Impact of `normalize_amount` (graph completeness: ok; analysis: partial):
  - depth 1: `test_refund_is_negative` in `tests/test_pipeline.py:13`, call site line 14 [CALLS, entire-graph] **confirmed** (CALLS edge with call site tests/test_pipeline.py:14)
  - depth 1: `test_purchase_is_positive` in `tests/test_pipeline.py:16`, call site line 17 [CALLS, entire-graph] **confirmed** (CALLS edge with call site tests/test_pipeline.py:17)
  - dynamic reference `pipeline/transactions.py:13` `"normalize": "normalize_amount",` [symbol name used as a string literal, ripple-scan] **needs-verification**
  - dynamic reference `pipeline/transactions.py:26` `fn = globals()[STEP_REGISTRY[step]]` [reflection/dynamic dispatch via globals(), ripple-scan] **needs-verification**
- Graph warnings:
  - `W_WORKTREE_SNAPSHOT`: snapshot records are read from the working tree because --worktree was requested

## 3. Affected data products (source = configured, ripple.toml)
- No configured entry point is reachable from the changed symbols according to the graph (analysis partial: executed as fallback).
- Entry point `pipeline.transactions:run` -> job `ripple_transactions_job` [fallback (graph did not reach it)]
  - Input: `workspace.ripple.raw_transactions`; outputs: `workspace.ripple.clean_transactions`, `workspace.ripple.daily_revenue`
  - Data products: Daily Revenue dashboard, Finance month-end close extract

## 4. Reproducible comparison (same input snapshot)
- `clean_transactions` (key `txn_id`): 0 of 150 rows changed [local execution of base and head]
- `daily_revenue` (key `txn_date`): 0 of 14 rows changed [local execution of base and head]
- Databricks comparison not run (local backend).
