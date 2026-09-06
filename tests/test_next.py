"""Follow-ups after the Curveball: head worktree, cross-file scan, CONFIGURES edges,
Databricks job execution (script + request shape only), Unity Catalog lineage parsing,
and execution-failure handling. No network in any test."""

import ast
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from ripple.card import NEEDS_VERIFICATION, ReviewCard, decide, render_markdown
from ripple.compare import TableDiff
from ripple.config import load_config
from ripple.databricks_backend import LINEAGE_SQL, _lit, parse_lineage
from ripple.databricks_job import render_job_script, submit_body
from ripple.graph import (ANALYSIS_PARTIAL, HEURISTIC, configures_references, parse_impact,
                          scan_cross_file_references, scan_set)
from ripple.intent import Intent
from ripple.worktree import head_tree

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"


def _files(*names):
    return {f"tests/fixtures/cross_file/{n}": (FIXTURES / "cross_file" / n).read_text() for n in names}


def _card(**kw):
    base = dict(base="main", head="x", intent=Intent("Refunds negative.", "pipeline/INTENT.md", "CP1", None, "intent-file"),
                changed=[], impacts=[], reached_entry_points=[], mappings=[], local_diffs=[], databricks=None)
    base.update(kw)
    return ReviewCard(**base)


class CrossFileScanTests(unittest.TestCase):
    def test_registry_in_yaml_plus_getattr_in_other_module_is_flagged(self):
        refs = scan_cross_file_references(_files("steps.yaml", "runner.py"), {"normalize_amount", "daily_revenue", "run_steps"})
        self.assertEqual(sorted(refs), ["daily_revenue", "normalize_amount"])
        r = refs["normalize_amount"][0]
        self.assertEqual((r.file_path, r.line), ("tests/fixtures/cross_file/steps.yaml", 3))
        self.assertIn("runner.py:7` dispatches via importlib", r.reason)
        self.assertTrue(r.reason.startswith("cross-file"))

    def test_yaml_comment_and_dotted_paths_do_not_count(self):
        files = {"a.yaml": "# normalize_amount only in a comment\nentry: pipeline.transactions.run\n",
                 "b.py": "x = getattr(m, n)\n"}
        self.assertEqual(scan_cross_file_references(files, {"normalize_amount", "run"}), {})

    def test_name_without_any_reflection_is_not_flagged(self):
        self.assertEqual(scan_cross_file_references(_files("steps.yaml"), {"normalize_amount"}), {})
        files = {"a.yaml": "steps: [normalize_amount]\n", "b.py": "def f():\n    return normalize_amount(1, 'x')\n"}
        self.assertEqual(scan_cross_file_references(files, {"normalize_amount"}), {})

    def test_same_file_pairs_are_left_to_the_single_file_scan(self):
        dyn = {"d.py": (FIXTURES / "transactions_dynamic_dispatch.py").read_text()}
        self.assertEqual(scan_cross_file_references(dyn, {"normalize_amount"}), {})

    def test_cross_file_reference_makes_impact_partial(self):
        refs = scan_cross_file_references(_files("steps.yaml", "runner.py"), {"normalize_amount"})
        imp = parse_impact(json.loads((FIXTURES / "graph_impact_dynamic.json").read_text()), "normalize_amount",
                           refs["normalize_amount"])
        self.assertEqual(imp.analysis, ANALYSIS_PARTIAL)
        self.assertTrue(any("cross-file" in r for r in imp.partial_reasons))

    def test_scan_set_covers_siblings_and_package_config(self):
        files = scan_set(ROOT, ["tests/fixtures/cross_file/runner.py"], ["pipeline/transactions.py"])
        self.assertIn("tests/fixtures/cross_file/steps.yaml", files)      # config next to the changed file
        self.assertIn("pipeline/__init__.py", files)                       # sibling of the entry file
        self.assertNotIn("ripple/execute.py", files)                       # unrelated packages stay out

    def test_static_repo_has_no_cross_file_reference(self):
        files = scan_set(ROOT, ["pipeline/transactions.py"], ["pipeline/transactions.py"])
        self.assertEqual(scan_cross_file_references(files, {"normalize_amount", "run"}), {})


class ConfiguresEdgeTests(unittest.TestCase):
    def test_configures_edge_is_reported_and_partial(self):
        data = json.loads((FIXTURES / "graph_impact_resolved.json").read_text())
        data["callers"]["entries"].append({"relation": "CONFIGURES", "depth": 1,
                                           "endpoint": {"name": "steps", "file_path": "pipeline/steps.yaml", "start_line": 2}})
        refs = configures_references(data)
        self.assertEqual([(r.file_path, r.line) for r in refs], [("pipeline/steps.yaml", 2)])
        imp = parse_impact(data, "normalize_amount")
        self.assertEqual(imp.analysis, ANALYSIS_PARTIAL)
        self.assertEqual(imp.callers[-1].evidence, HEURISTIC)             # non-structural relation
        self.assertTrue(any("CONFIGURES" in r for r in imp.partial_reasons))


class HeadWorktreeTests(unittest.TestCase):
    def _repo(self):
        tmp = Path(tempfile.mkdtemp(prefix="ripple-wt-test-"))
        def git(*a):
            subprocess.run(["git", *a], cwd=tmp, check=True, capture_output=True,
                           env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                                "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"})
        git("init", "-q", "-b", "main")
        (tmp / "f.py").write_text("v = 1\n")
        git("add", "f.py"); git("-c", "commit.gpgsign=false", "commit", "-q", "-m", "one")
        git("checkout", "-q", "-b", "feature")
        (tmp / "f.py").write_text("v = 2\n")
        git("-c", "commit.gpgsign=false", "commit", "-q", "-am", "two")
        git("checkout", "-q", "main")
        return tmp

    def test_worktree_materialises_head_and_cleans_up(self):
        repo = self._repo()
        with head_tree(repo, "feature") as ht:
            self.assertTrue(ht.is_worktree)
            self.assertEqual((ht.path / "f.py").read_text(), "v = 2\n")
            self.assertEqual((repo / "f.py").read_text(), "v = 1\n")        # checkout untouched
            self.assertIn("temporary worktree", ht.note)
            path = ht.path
        self.assertFalse(path.exists())
        listed = subprocess.run(["git", "worktree", "list"], cwd=repo, capture_output=True, text=True).stdout
        self.assertNotIn("ripple-head-", listed)

    def test_checked_out_head_needs_no_worktree(self):
        repo = self._repo()
        with head_tree(repo, "main") as ht:
            self.assertFalse(ht.is_worktree)
            self.assertEqual(ht.path, repo)

    def test_disabled_uses_checkout_and_says_so(self):
        repo = self._repo()
        with head_tree(repo, "feature", enabled=False) as ht:
            self.assertFalse(ht.is_worktree)
            self.assertIn("--no-worktree", ht.note)


class DatabricksJobTests(unittest.TestCase):
    def test_script_embeds_both_sources_and_parses(self):
        s = render_job_script("main..x@1", "pipeline/transactions.py", "run", "BASE_SRC = 1\n", "HEAD_SRC = 2\n")
        ast.parse(s)
        self.assertIn("BASE_SRC = 1", s)
        self.assertIn("HEAD_SRC = 2", s)
        self.assertIn("RUN_ID = 'main..x@1'", s)
        self.assertIn("raw_transactions", s)
        self.assertIn("saveAsTable", s)                                    # Spark write => UC lineage recorded

    def test_submit_body_is_serverless_single_task(self):
        b = submit_body("ripple x", "/Workspace/Users/u/ripple/a.py")
        self.assertEqual(b["tasks"][0]["spark_python_task"]["python_file"], "/Workspace/Users/u/ripple/a.py")
        self.assertEqual(b["tasks"][0]["environment_key"], b["environments"][0]["environment_key"])
        self.assertNotIn("new_cluster", b["tasks"][0])
        self.assertNotIn("existing_cluster_id", b["tasks"][0])


class LineageTests(unittest.TestCase):
    COLS = ["source_table_full_name", "target_table_full_name", "entity_type", "entity_id", "last_seen", "events"]

    def test_parse_upstream_downstream_and_readers(self):
        ours = ["workspace.ripple.raw_transactions", "workspace.ripple.clean_transactions", "workspace.ripple.daily_revenue"]
        rows = [
            ["workspace.ripple.raw_transactions", "workspace.ripple.clean_transactions", "JOB", "1", "t1", "2"],
            ["workspace.ripple.daily_revenue", "workspace.finance.month_end", "NOTEBOOK", "9", "t2", "1"],
            ["workspace.ripple.daily_revenue", None, "DASHBOARD", "d1", "t3", "4"],
            ["workspace.ripple.daily_revenue", None, None, None, "t4", "7"],                # ad-hoc read
            ["workspace.landing.txns", "workspace.ripple.raw_transactions", "JOB", "2", "t5", "1"],
        ]
        lin = parse_lineage(ours, self.COLS, rows)
        self.assertTrue(lin["available"])
        self.assertEqual(lin["downstream_tables"], ["workspace.finance.month_end"])
        self.assertEqual(lin["upstream_tables"], ["workspace.landing.txns"])
        self.assertEqual(lin["readers"], ["DASHBOARD:d1"])
        self.assertEqual(len(lin["edges"]), 5)

    def test_sql_filters_by_table_and_window(self):
        sql = LINEAGE_SQL.format(days=30, tables=_lit("a.b.c"))
        self.assertIn("system.access.table_lineage", sql)
        self.assertIn("IN ('a.b.c')", sql)
        self.assertIn("DATE_SUB(CURRENT_TIMESTAMP(), 30)", sql)

    def test_card_renders_lineage_and_unavailable(self):
        lin = parse_lineage(["a.b.c"], self.COLS, [["a.b.c", "a.b.d", "JOB", "1", "t", "1"]])
        lin.update({"days": 30, "statement_id": "s1"})
        md = render_markdown(_card(lineage=lin))
        self.assertIn("unity-catalog-lineage", md)
        self.assertIn("downstream table: configured tables -> `a.b.d` **confirmed** (observed write)", md)
        md2 = render_markdown(_card(lineage={"available": False, "error": "no system tables"}))
        self.assertIn("unavailable (no system tables)", md2)


class ExecutionTests(unittest.TestCase):
    def test_execution_failure_without_comparison_needs_verification(self):
        c = _card(execution_errors=["pipeline.transactions:run: SyntaxError: bad base"])
        self.assertTrue(decide(c).startswith(NEEDS_VERIFICATION))
        self.assertIn("Execution error", render_markdown(c))

    def test_job_run_shown_on_card(self):
        c = _card(local_diffs=[TableDiff("clean_transactions", "txn_id", 150, 150, 0, 0, 0)],
                  execution_mode="databricks-job",
                  job_run={"run_id": 7, "result_state": "SUCCESS", "duration_s": 61.0, "run_page_url": "https://x/run/7",
                           "python_file": "/Workspace/Users/u/ripple/a.py"})
        c.verdict = decide(c)
        md = render_markdown(c)
        self.assertIn("as a Databricks job", md)
        self.assertIn("execution `databricks-job`", md)
        self.assertTrue(c.verdict.startswith("PASS"))

    def test_config_scan_section_is_optional(self):
        cfg = load_config(ROOT)
        self.assertEqual(cfg.scan.config_files, [])


if __name__ == "__main__":
    unittest.main()
