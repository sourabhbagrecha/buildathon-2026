# Data

`raw_transactions.csv` is **SYNTHETIC** data generated deterministically by
`generate_snapshot.py` (seed 2026, 150 rows). Columns: `txn_id, txn_date, customer_id,
kind (purchase|refund), amount` where `amount` is the positive magnitude; the sign is
derived by the pipeline. No real customer data is involved.

Regenerate: `python3 data/generate_snapshot.py`
