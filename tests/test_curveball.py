"""Curveball: the graph can miss callers (dynamic dispatch, reflection, degraded runs).

Ripple must label every relationship (confirmed / heuristic / needs-verification), flag partial
analysis on the card, and execute the configured entry points anyway instead of reporting PASS
on graph evidence alone.
"""

import json
import unittest
from pathlib import Path

from ripple.card import BLOCK, NEEDS_VERIFICATION, PASS, ReviewCard, decide, render_markdown
from ripple.cli import select_mappings
from ripple.compare import TableDiff, compare_outputs
from ripple.config import Mapping
from ripple.execute import load_module_from_source, load_snapshot
from ripple.graph import (ANALYSIS_COMPLETE, ANALYSIS_PARTIAL, CONFIRMED, HEURISTIC, NEEDS_VERIFICATION as NV,
                          analysis_state, label_caller, parse_impact, reachable_entry_points,
                          scan_dynamic_references)
from ripple.intent import Intent

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
DYN = "tests/fixtures/transactions_dynamic_dispatch.py"


def _impact(name, refs=None):
    return parse_impact(json.loads((FIXTURES / name).read_text()), "normalize_amount", refs)


def _mapping():
    return Mapping(source="configured", entry_point="pipeline.transactions:run", entry_file="pipeline/transactions.py",
                   databricks_job="j", databricks_warehouse_id="w", input_table="i", output_tables=["o"],
                   data_products=["d"], intent_file="pipeline/INTENT.md", intent_checkpoint="CP", intent_query="q")


def _card(diffs, impacts=(), analysis=ANALYSIS_COMPLETE, reasons=(), fallback=()):
    return ReviewCard(base="main", head="x", intent=Intent("Refunds negative.", "pipeline/INTENT.md", "CP1", None, "intent-file"),
                      changed=[], impacts=list(impacts), reached_entry_points=[], mappings=[], local_diffs=diffs,
                      databricks=None, analysis=analysis, partial_reasons=list(reasons), fallback_entry_points=list(fallback))


class EvidenceLabelTests(unittest.TestCase):
    def test_resolved_graph_is_complete_and_confirmed(self):
        imp = _impact("graph_impact_resolved.json")
        self.assertEqual(imp.analysis, ANALYSIS_COMPLETE)
        self.assertEqual({c.evidence for c in imp.callers}, {CONFIRMED})
        self.assertIn("call site pipeline/transactions.py:62", [c.evidence_reason for c in imp.callers][1])

    def test_degraded_graph_run_is_partial_and_heuristic(self):
        imp = _impact("graph_impact_degraded.json")
        self.assertEqual(imp.analysis, ANALYSIS_PARTIAL)
        self.assertTrue(any("completeness_level is 'partial'" in r for r in imp.partial_reasons))
        self.assertTrue(any("E_PARSE_TIMEOUT" in r for r in imp.partial_reasons))
        self.assertTrue(any("W_UNRESOLVED_CALLS" in r for r in imp.partial_reasons))
        self.assertEqual([c.evidence for c in imp.callers], [HEURISTIC])   # DATA_FLOWS, not CALLS
        # a heuristic edge still counts as "reached" but the label travels with it
        self.assertEqual(reachable_entry_points(imp, {"run"})[0].evidence, HEURISTIC)

    def test_call_edge_without_call_site_needs_verification(self):
        ev, why = label_caller({"relation": "CALLS", "endpoint": {"name": "run"}}, graph_partial=False)
        self.assertEqual(ev, NV)
        self.assertIn("without a call site", why)

    def test_call_edge_in_partial_run_is_heuristic(self):
        ev, _ = label_caller({"relation": "CALLS", "call_site": {"line": 3}}, graph_partial=True)
        self.assertEqual(ev, HEURISTIC)

    def test_benign_worktree_warning_does_not_make_analysis_partial(self):
        imp = _impact("graph_impact_resolved.json")
        self.assertEqual([w["code"] for w in imp.warnings], ["W_WORKTREE_SNAPSHOT"])
        self.assertEqual(imp.partial_reasons, [])


class DynamicDispatchTests(unittest.TestCase):
    """Real `entire graph impact` output for the dynamic fixture: 0 callers, completeness 'ok'.

    The graph does not know it missed anything, so Ripple's own scan has to supply the signal.
    """

    def test_graph_alone_silently_misses_the_entry_point(self):
        imp = _impact("graph_impact_dynamic.json")
        self.assertEqual(imp.callers, [])
        self.assertEqual(imp.completeness_level, "ok")
        self.assertEqual(reachable_entry_points(imp, {"run"}), [])

    def test_scan_finds_registry_and_getattr(self):
        refs = scan_dynamic_references((ROOT / DYN).read_text(), "normalize_amount", DYN)
        reasons = {r.reason for r in refs}
        self.assertIn("symbol name used as a string literal", reasons)
        self.assertIn("reflection/dynamic dispatch via globals()", reasons)
        self.assertIn(13, [r.line for r in refs])   # STEP_REGISTRY entry

    def test_scan_ignores_docstrings_and_comments(self):
        src = '"""uses getattr() and "run" in prose"""\n# getattr(m, "run")\nSTEPS = {"x": "run"}\n'
        self.assertEqual(scan_dynamic_references(src, "run", "f.py"), [])

    def test_scan_regex_fallback_when_file_does_not_parse(self):
        refs = scan_dynamic_references('def f(:\n    x = getattr(m, "run")\n', "run", "bad.py")
        self.assertEqual({r.reason for r in refs}, {"symbol name used as a string literal",
                                                    "reflection/dynamic dispatch via getattr"})

    def test_scan_needs_both_signals(self):
        static = (ROOT / "pipeline" / "transactions.py").read_text()
        # `{"clean_transactions": clean}` is a dict key sharing a function name; no reflection in file
        self.assertEqual(scan_dynamic_references(static, "clean_transactions", "pipeline/transactions.py"), [])
        self.assertEqual(scan_dynamic_references(static, "normalize_amount", "pipeline/transactions.py"), [])
        self.assertEqual(scan_dynamic_references("x = getattr(m, name)\n", "run", "f.py"), [])

    def test_scan_makes_analysis_partial(self):
        refs = scan_dynamic_references((ROOT / DYN).read_text(), "normalize_amount", DYN)
        imp = _impact("graph_impact_dynamic.json", refs)
        self.assertEqual(imp.analysis, ANALYSIS_PARTIAL)
        self.assertTrue(all("cannot resolve" in r for r in imp.partial_reasons))
        state, reasons = analysis_state([imp])
        self.assertEqual(state, ANALYSIS_PARTIAL)
        self.assertTrue(reasons[0].startswith("normalize_amount: dynamic reference"))

    def test_failed_impact_query_counts_as_partial(self):
        state, reasons = analysis_state([_impact("graph_impact_resolved.json")], failed=1)
        self.assertEqual(state, ANALYSIS_PARTIAL)
        self.assertIn("1 impact query failed", reasons)

    def test_fixture_executes_and_matches_static_pipeline(self):
        rows = load_snapshot(ROOT / "data" / "raw_transactions.csv")
        dyn = load_module_from_source((ROOT / DYN).read_text(), "dyn")
        static = load_module_from_source((ROOT / "pipeline" / "transactions.py").read_text(), "static")
        diffs = compare_outputs(static.run([dict(r) for r in rows]), dyn.run([dict(r) for r in rows]),
                                {"clean_transactions": "txn_id", "daily_revenue": "txn_date"})
        self.assertTrue(all(d.rows_changed == 0 for d in diffs))


class FallbackTests(unittest.TestCase):
    def test_partial_analysis_executes_unreached_entry_points(self):
        chosen, fallback = select_mappings([_mapping()], set(), ANALYSIS_PARTIAL, has_code_changes=True)
        self.assertEqual([m.entry_point for m in chosen], ["pipeline.transactions:run"])
        self.assertEqual(fallback, ["pipeline.transactions:run"])

    def test_complete_analysis_executes_only_reached(self):
        self.assertEqual(select_mappings([_mapping()], set(), ANALYSIS_COMPLETE, True), ([], []))
        chosen, fallback = select_mappings([_mapping()], {"run"}, ANALYSIS_COMPLETE, True)
        self.assertEqual(len(chosen), 1)
        self.assertEqual(fallback, [])

    def test_partial_without_code_changes_does_not_execute(self):
        self.assertEqual(select_mappings([_mapping()], set(), ANALYSIS_PARTIAL, False), ([], []))


class VerdictTests(unittest.TestCase):
    def test_partial_without_execution_never_passes(self):
        v = decide(_card([], analysis=ANALYSIS_PARTIAL, reasons=["r"]))
        self.assertTrue(v.startswith(NEEDS_VERIFICATION))

    def test_partial_verified_by_execution_passes_with_caveat(self):
        v = decide(_card([TableDiff("clean_transactions", "txn_id", 150, 150, 0, 0, 0)], analysis=ANALYSIS_PARTIAL, reasons=["r"]))
        self.assertTrue(v.startswith(PASS))
        self.assertIn("verified by execution", v)

    def test_partial_with_changed_rows_blocks(self):
        v = decide(_card([TableDiff("clean_transactions", "txn_id", 150, 150, 33, 0, 0)], analysis=ANALYSIS_PARTIAL))
        self.assertTrue(v.startswith(BLOCK))

    def test_complete_unreached_passes_on_confirmed_graph(self):
        v = decide(_card([]))
        self.assertTrue(v.startswith(PASS))
        self.assertIn("all relations confirmed", v)


class CardRenderTests(unittest.TestCase):
    def test_banner_and_labels_on_partial_card(self):
        refs = scan_dynamic_references((ROOT / DYN).read_text(), "normalize_amount", DYN)
        imp = _impact("graph_impact_dynamic.json", refs)
        c = _card([TableDiff("clean_transactions", "txn_id", 150, 150, 33, 0, 0)], impacts=[imp],
                  analysis=ANALYSIS_PARTIAL, reasons=imp.partial_reasons, fallback=["pipeline.transactions:run"])
        c.verdict = decide(c)
        md = render_markdown(c)
        self.assertIn("PARTIAL ANALYSIS", md)
        self.assertIn("absence of callers is not evidence of safety", md)
        self.assertIn("Fallback: executed configured entry point(s) `pipeline.transactions:run`", md)
        self.assertIn("ripple-scan] **needs-verification**", md)
        self.assertIn("analysis `partial`", md)

    def test_no_banner_on_complete_card(self):
        imp = _impact("graph_impact_resolved.json")
        c = _card([TableDiff("clean_transactions", "txn_id", 150, 150, 0, 0, 0)], impacts=[imp])
        c.verdict = decide(c)
        md = render_markdown(c)
        self.assertNotIn("PARTIAL ANALYSIS", md)
        self.assertIn("**confirmed**", md)
        self.assertIn("2 confirmed, 0 heuristic, 0 needs-verification", md)


if __name__ == "__main__":
    unittest.main()
