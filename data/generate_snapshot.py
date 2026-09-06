"""Generate the SYNTHETIC raw_transactions snapshot deterministically (seed 2026)."""

from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from pathlib import Path

SEED = 2026
N_ROWS = 150
OUT = Path(__file__).with_name("raw_transactions.csv")


def generate(n: int = N_ROWS, seed: int = SEED) -> list[dict]:
    rng = random.Random(seed)
    start = date(2026, 8, 1)
    rows = []
    for i in range(1, n + 1):
        kind = "refund" if rng.random() < 0.28 else "purchase"
        amount = round(rng.uniform(5, 250), 2) if kind == "purchase" else round(rng.uniform(5, 120), 2)
        rows.append(
            {
                "txn_id": f"T{i:04d}",
                "txn_date": (start + timedelta(days=rng.randint(0, 13))).isoformat(),
                "customer_id": f"C{rng.randint(1, 40):03d}",
                "kind": kind,
                "amount": amount,
            }
        )
    return rows


def main() -> None:
    rows = generate()
    with OUT.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["txn_id", "txn_date", "customer_id", "kind", "amount"])
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} rows to {OUT}")


if __name__ == "__main__":
    main()
