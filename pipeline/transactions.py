"""Transaction pipeline with DYNAMIC DISPATCH (Curveball fixture).

Same behaviour as pipeline/transactions.py, but the steps are looked up
through a string registry with ``globals()`` / ``getattr``. A static call
graph cannot see that ``run`` reaches ``normalize_amount``.
"""

from __future__ import annotations

from collections import defaultdict

STEP_REGISTRY = {
    "normalize": "normalize_amount",
    "clean": "clean_transactions",
    "aggregate": "daily_revenue",
}


def normalize_amount(amount: float, kind: str) -> float:
    magnitude = round(float(amount), 2)
    sign = -1 if kind == "refund" else 1
    return sign * magnitude


def apply_step(step: str, *args):
    """Resolve a step by name at runtime (reflection: invisible to the static graph)."""
    fn = globals()[STEP_REGISTRY[step]]
    return fn(*args)


def clean_transactions(rows) -> list[dict]:
    out = []
    for row in rows:
        kind = str(row["kind"]).strip().lower()
        out.append(
            {
                "txn_id": str(row["txn_id"]),
                "txn_date": str(row["txn_date"]),
                "customer_id": str(row["customer_id"]),
                "kind": kind,
                "amount": apply_step("normalize", row["amount"], kind),
            }
        )
    out.sort(key=lambda r: r["txn_id"])
    return out


def daily_revenue(clean_rows) -> list[dict]:
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
    """Pipeline entry point: every step goes through the registry."""
    clean = apply_step("clean", raw_rows)
    return {"clean_transactions": clean, "daily_revenue": apply_step("aggregate", clean)}
