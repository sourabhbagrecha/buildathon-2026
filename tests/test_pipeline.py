import unittest
from pathlib import Path

from pipeline.transactions import daily_revenue, normalize_amount, run
from ripple.execute import load_snapshot

REPO = Path(__file__).resolve().parents[1]


class PipelineIntentTests(unittest.TestCase):
    """Intent (checkpoint 01M1TVFK5MAS7B1JFN41QA2JQ8): refunds must remain negative."""

    def test_refund_is_negative(self):
        self.assertEqual(normalize_amount(62.79, "refund"), -62.79)

    def test_purchase_is_positive(self):
        self.assertEqual(normalize_amount(224.23, "purchase"), 224.23)

    def test_daily_revenue_is_net_of_refunds(self):
        clean = [
            {"txn_date": "2026-08-01", "amount": 100.0},
            {"txn_date": "2026-08-01", "amount": -40.0},
        ]
        self.assertEqual(daily_revenue(clean), [{"txn_date": "2026-08-01", "net_revenue": 60.0, "txn_count": 2}])

    def test_snapshot_run_has_negative_refunds(self):
        rows = load_snapshot(REPO / "data" / "raw_transactions.csv")
        out = run(rows)
        refunds = [r for r in out["clean_transactions"] if r["kind"] == "refund"]
        self.assertTrue(refunds)
        self.assertTrue(all(r["amount"] < 0 for r in refunds))
        self.assertEqual(len(out["clean_transactions"]), 150)


if __name__ == "__main__":
    unittest.main()
