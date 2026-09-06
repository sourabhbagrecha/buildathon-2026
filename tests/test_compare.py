import unittest
from pathlib import Path

from pipeline import transactions as base_mod
from ripple.compare import compare_outputs, compare_table
from ripple.execute import load_module_from_source, load_snapshot

REPO = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
KEYS = {"clean_transactions": "txn_id", "daily_revenue": "txn_date"}


class CompareTests(unittest.TestCase):
    def setUp(self):
        self.rows = load_snapshot(REPO / "data" / "raw_transactions.csv")
        self.head_mod = load_module_from_source(
            (FIXTURES / "transactions_abs_regression.py").read_text(), "head_abs")

    def test_identical_versions_produce_no_diff(self):
        out = base_mod.run(self.rows)
        diffs = compare_outputs(out, base_mod.run(self.rows), KEYS)
        self.assertTrue(all(d.rows_changed == 0 for d in diffs))

    def test_seeded_abs_regression_is_detected(self):
        base_out = base_mod.run(self.rows)
        head_out = self.head_mod.run(self.rows)
        diffs = {d.table: d for d in compare_outputs(base_out, head_out, KEYS)}
        clean = diffs["clean_transactions"]
        refunds = sum(1 for r in base_out["clean_transactions"] if r["kind"] == "refund")
        self.assertEqual(clean.rows_changed, refunds)          # exactly the refund rows flipped sign
        self.assertGreater(clean.numeric_delta["amount"], 0)   # revenue overstated
        daily = diffs["daily_revenue"]
        self.assertGreater(daily.rows_changed, 0)
        self.assertAlmostEqual(daily.numeric_delta["net_revenue"], clean.numeric_delta["amount"], places=2)

    def test_missing_and_extra_rows_are_counted(self):
        base = [{"k": "a", "v": 1}, {"k": "b", "v": 2}]
        head = [{"k": "a", "v": 1}, {"k": "c", "v": 3}]
        d = compare_table("t", "k", base, head)
        self.assertEqual((d.rows_changed, d.only_in_base, d.only_in_head), (0, 1, 1))


if __name__ == "__main__":
    unittest.main()
