"""Transaction transformation pipeline (pure Python, stdlib only).

INTENT (see pipeline/INTENT.md, Entire checkpoint 01M1TVFK5MAS7B1JFN41QA2JQ8):
purchases are stored as positive amounts and refunds MUST remain negative so that
daily net revenue = sum(amount) is correct.
"""

from __future__ import annotations

from collections import defaultdict


def normalize_amount(amount: float, kind: str) -> float:
    """Return the signed amount for a transaction.

    Purchases are positive, refunds are negative. The raw feed stores the
    magnitude only, so the sign is derived from ``kind``.
    Documented intent: refunds must remain negative.
    """
    # Normalize transaction amounts: coerce to a clean non-negative magnitude.
    magnitude = round(abs(float(amount)), 2)
    if kind == "refund":
        return abs(-magnitude)
    return magnitude


def clean_transactions(rows) -> list[dict]:
    """Produce clean_transactions rows from raw rows.

    Each raw row has: txn_id, txn_date, customer_id, kind, amount (magnitude).
    """
    out = []
    for row in rows:
        kind = str(row["kind"]).strip().lower()
        out.append(
            {
                "txn_id": str(row["txn_id"]),
                "txn_date": str(row["txn_date"]),
                "customer_id": str(row["customer_id"]),
                "kind": kind,
                "amount": normalize_amount(row["amount"], kind),
            }
        )
    out.sort(key=lambda r: r["txn_id"])
    return out


def daily_revenue(clean_rows) -> list[dict]:
    """Aggregate net revenue (sum of signed amounts) and row count per day."""
    totals: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    for row in clean_rows:
        totals[row["txn_date"]] += row["amount"]
        counts[row["txn_date"]] += 1
    return [
        {"txn_date": day, "net_revenue": round(totals[day], 2), "txn_count": counts[day]}
        for day in sorted(totals)
    ]


def run(raw_rows) -> dict:
    """Pipeline entry point. Mapped to Databricks job in ripple.toml."""
    clean = clean_transactions(raw_rows)
    return {"clean_transactions": clean, "daily_revenue": daily_revenue(clean)}
