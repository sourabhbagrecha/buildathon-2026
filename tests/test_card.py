import unittest

from ripple.card import ReviewCard, decide, render_markdown
from ripple.compare import TableDiff
from ripple.intent import Intent


def _card(diffs):
    return ReviewCard(base="main", head="x", intent=Intent("Refunds must remain negative.", "pipeline/INTENT.md", "CP1", None, "intent-file"),
                      changed=[], impacts=[], reached_entry_points=[], mappings=[], local_diffs=diffs, databricks=None)


class CardTests(unittest.TestCase):
    def test_pass_when_no_diff(self):
        c = _card([TableDiff("clean_transactions", "txn_id", 150, 150, 0, 0, 0)])
        self.assertTrue(decide(c).startswith("PASS"))

    def test_block_when_rows_change(self):
        c = _card([TableDiff("clean_transactions", "txn_id", 150, 150, 33, 0, 0, numeric_delta={"amount": 4179.72})])
        c.verdict = decide(c)
        self.assertTrue(c.verdict.startswith("BLOCK"))
        md = render_markdown(c)
        for section in ("Original requirement", "Source locations", "Affected data products", "Reproducible comparison"):
            self.assertIn(section, md)
        self.assertIn("33 of 150 rows changed", md)


if __name__ == "__main__":
    unittest.main()
