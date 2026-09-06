# Ripple review card: `268c4ec` -> `demo/abs-normalize`

**Verdict:** BLOCK: downstream data changed meaning; review against the stated intent

**Evidence:** analysis `complete`; graph relations: 4 confirmed, 0 heuristic, 0 needs-verification; execution `databricks-job`
- graph analysed `demo/abs-normalize` (1c3dcc001789) in a temporary worktree, not the checked-out tree; scanned 2 file(s) for dynamic references

## 1. Original requirement (intent)
- Requirement: Refunds must remain negative. `normalize_amount` derives the sign of an amount from the transaction kind: purchases positive, refunds negative. Daily net revenue (`daily_revenue`) is `sum(amount)` per day and is only correct if this holds.
- Source: `pipeline/INTENT.md`, Entire checkpoint `01M1TVFK5MAS7B1JFN41QA2JQ8` (`entire checkpoint explain 01M1TVFK5MAS7B1JFN41QA2JQ8`) [intent-file+checkpoint]
- Checkpoint excerpt: "...w transformations against the same input snapshot.

The demo: A checkpoint says refunds must remain negative. An agent introduces abs(amount) while “normalizing transaction amounts.” Ripple traces the changed helper to the transaction pipeline, executes both versions, and shows p..."

## 2. Source locations (Entire Graph, source = entire-graph)
- Changed function `normalize_amount` in `pipeline/transactions.py:13` (body_changed, graph dependents: 33)
- Impact of `normalize_amount` (graph completeness: ok; analysis: complete):
  - depth 1: `clean_transactions` in `pipeline/transactions.py:27`, call site line 41 [CALLS, entire-graph] **confirmed** (CALLS edge with call site pipeline/transactions.py:41)
  - depth 1: `test_refund_is_negative` in `tests/test_pipeline.py:13`, call site line 14 [CALLS, entire-graph] **confirmed** (CALLS edge with call site tests/test_pipeline.py:14)
  - depth 1: `test_purchase_is_positive` in `tests/test_pipeline.py:16`, call site line 17 [CALLS, entire-graph] **confirmed** (CALLS edge with call site tests/test_pipeline.py:17)
  - depth 2: `run` in `pipeline/transactions.py:61` via `clean_transactions`, call site line 63 [CALLS, entire-graph] **confirmed** (CALLS edge with call site pipeline/transactions.py:63)
- Graph warnings:
  - `W_WORKTREE_SNAPSHOT`: snapshot records are read from the working tree because --worktree was requested

## 3. Affected data products (source = configured, ripple.toml)
- Entry point `pipeline.transactions:run` -> job `ripple_transactions_job` [reached: confirmed]
  - Input: `workspace.ripple.raw_transactions`; outputs: `workspace.ripple.clean_transactions`, `workspace.ripple.daily_revenue`
  - Data products: Daily Revenue dashboard, Finance month-end close extract
- Unity Catalog lineage (source = unity-catalog-lineage, **observed** over the last 30 days, statement `01f1a9d5-c2a2-1fcb-a48a-2fcccd94ca40`):
  - no table-to-table flows or named readers observed; only ad-hoc reads/writes. Absence of lineage is not evidence of no consumers.

## 4. Reproducible comparison (same input snapshot)
- Both versions executed **as a Databricks job** (serverless one-time run `43140873411386`, SUCCESS, 52.1 s): https://dbc-d87cc10e-1ac0.cloud.databricks.com/?o=7474652145876856#job/399281511823673/run/43140873411386
  - script: `/Workspace/Users/sourabhbagrecha@gmail.com/ripple/ripple_exec_268c4ec..demo_abs-normalize_20260906T092954Z.py` (local copy `evidence/databricks/jobs/ripple_exec_268c4ec..demo_abs-normalize_20260906T092954Z.py`); reads `raw_transactions`, writes `clean_transactions` and `daily_revenue` for `version = base|head`
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
- Databricks (`workspace.ripple`, run_id `268c4ec..demo/abs-normalize@20260906T092954Z`, warehouse `c9a0bd38022ced72`):
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
  - SQL statement ids: {"row_diff": "01f1a9d5-b90b-1ecb-8dd0-4ed0839bb942", "agg_diff": "01f1a9d5-bd1a-166d-b3de-cc56fae78a03", "summary": "01f1a9d5-c0e3-14ee-941a-8c80c4f93098"}
  - Reproduce: `python3 -m ripple review --base 268c4ec --head demo/abs-normalize --backend databricks --execute databricks`
