# Ripple review card: `demo/dynamic-dispatch` -> `demo/dynamic-dispatch-abs`

**Verdict:** BLOCK: downstream data changed meaning; review against the stated intent

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
- Changed function `normalize_amount` in `pipeline/transactions.py:19` (signature_changed, graph dependents: 13)
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
- `clean_transactions` (key `txn_id`): 33 of 150 rows changed, numeric delta {"amount": 4179.72} [local execution of base and head]
  - txn_id=T0001 amount: -62.79 -> 62.79
  - txn_id=T0010 amount: -66.88 -> 66.88
  - txn_id=T0011 amount: -79.15 -> 79.15
  - txn_id=T0025 amount: -80.4 -> 80.4
  - txn_id=T0027 amount: -60.84 -> 60.84
  - ... 28 more
- `daily_revenue` (key `txn_date`): 13 of 14 rows changed, numeric delta {"net_revenue": 4179.72} [local execution of base and head]
  - txn_date=2026-08-01 net_revenue: 1128.01 -> 1359.33
  - txn_date=2026-08-02 net_revenue: 1294.9 -> 1490.24
  - txn_date=2026-08-03 net_revenue: 545.25 -> 1106.15
  - txn_date=2026-08-04 net_revenue: 471.12 -> 577.94
  - txn_date=2026-08-05 net_revenue: 703.64 -> 1046.76
  - ... 8 more
- Databricks (`workspace.ripple`, run_id `demo/dynamic-dispatch..demo/dynamic-dispatch-abs@20260906T085304Z`, warehouse `c9a0bd38022ced72`):
  - clean_transactions rows: base 150, head 150; rows differing: 33
  - total net revenue: base 13854.1 -> head 18033.82
  - 2026-08-01: 1128.01 -> 1359.33 (delta 231.32)
  - 2026-08-02: 1294.9 -> 1490.24 (delta 195.34)
  - 2026-08-03: 545.25 -> 1106.15 (delta 560.9)
  - 2026-08-04: 471.12 -> 577.94 (delta 106.82)
  - 2026-08-05: 703.64 -> 1046.76 (delta 343.12)
  - 2026-08-06: 1452.35 -> 1659.75 (delta 207.4)
  - 2026-08-07: 929.14 -> 1111.08 (delta 181.94)
  - 2026-08-08: 910.36 -> 1063.72 (delta 153.36)
  - 2026-08-09: 900.12 -> 1618.88 (delta 718.76)
  - 2026-08-10: 372.75 -> 923.81 (delta 551.06)
  - 2026-08-11: 2859.95 -> 3282.51 (delta 422.56)
  - 2026-08-12: -135.29 -> 135.29 (delta 270.58)
  - 2026-08-13: 1082.96 -> 1319.52 (delta 236.56)
  - SQL statement ids: {"row_diff": "01f1a9d0-7b86-195d-811e-54be0372247e", "agg_diff": "01f1a9d0-8014-1c7c-98de-d38ef52802df", "summary": "01f1a9d0-81c2-1ee3-ae2e-35fb4fbfcb94"}
  - Reproduce: `python3 -m ripple review --base demo/dynamic-dispatch --head demo/dynamic-dispatch-abs --backend databricks`
