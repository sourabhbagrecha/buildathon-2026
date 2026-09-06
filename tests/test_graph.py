import json
import unittest
from pathlib import Path

from ripple.graph import parse_diff, parse_impact, reachable_entry_points

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class GraphWrapperTests(unittest.TestCase):
    """Fully resolved code: static Python calls, no warnings beyond the worktree snapshot notice."""

    def test_parse_diff_finds_changed_symbol(self):
        d = parse_diff(json.loads((FIXTURES / "graph_diff_resolved.json").read_text()), "main", "demo")
        self.assertEqual([c.name for c in d.changed], ["normalize_amount"])
        self.assertEqual(d.changed[0].file_path, "pipeline/transactions.py")
        self.assertEqual(d.changed[0].change_type, "body_changed")

    def test_parse_impact_reaches_entry_point(self):
        imp = parse_impact(json.loads((FIXTURES / "graph_impact_resolved.json").read_text()), "normalize_amount")
        self.assertEqual([c.name for c in imp.callers], ["clean_transactions", "run"])
        self.assertEqual(imp.completeness_level, "ok")
        self.assertEqual(imp.partial_failures, [])
        reached = reachable_entry_points(imp, {"run"})
        self.assertEqual(len(reached), 1)
        self.assertEqual(reached[0].via, "clean_transactions")
        self.assertEqual(reached[0].call_site_line, 62)

    def test_no_entry_point_reached(self):
        imp = parse_impact(json.loads((FIXTURES / "graph_impact_resolved.json").read_text()), "normalize_amount")
        self.assertEqual(reachable_entry_points(imp, {"other_entry"}), [])


if __name__ == "__main__":
    unittest.main()
