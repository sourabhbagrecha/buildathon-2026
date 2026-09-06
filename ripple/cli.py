"""ripple CLI: `python3 -m ripple review --base main --head <rev> [--backend local|databricks]`."""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from ripple import card as cardmod
from ripple.compare import compare_outputs
from ripple.config import Mapping, load_config
from ripple.databricks_backend import DatabricksError, compare_run, ensure_tables, publish_run, save_evidence
from ripple.execute import load_snapshot, run_entry_point
from ripple.graph import ANALYSIS_PARTIAL, GraphError, analysis_state, graph_diff, graph_impact, reachable_entry_points
from ripple.intent import lookup_intent


def select_mappings(mappings: list[Mapping], reached_names: set[str], analysis: str,
                    has_code_changes: bool) -> tuple[list[Mapping], list[str]]:
    """Which configured entry points to execute.

    Reached ones always. When analysis is partial and code changed, every other configured
    entry point too (safe fallback): a caller edge the graph cannot see must not read as safe,
    and execute-and-compare is the verification path. Returns (mappings, fallback entry points).
    """
    chosen = [m for m in mappings if m.entry_symbol in reached_names]
    fallback: list[str] = []
    if analysis == ANALYSIS_PARTIAL and has_code_changes:
        for m in mappings:
            if m.entry_symbol not in reached_names:
                chosen.append(m)
                fallback.append(m.entry_point)
    return chosen, fallback


def review(repo: Path, base: str, head: str, backend: str, out: Path | None, use_entire: bool = True) -> cardmod.ReviewCard:
    cfg = load_config(repo)
    notes: list[str] = []

    # [1] semantic diff
    diff = graph_diff(repo, base, head)
    # [2] impact per changed symbol; Ripple also scans the changed file and the configured
    #     entry files for dynamic references the graph cannot resolve.
    impacts = []
    failed = 0
    scan_files = [m.entry_file for m in cfg.mappings]
    code_changes = [ch for ch in diff.changed if ch.is_code]
    skipped = len(diff.changed) - len(code_changes)
    if skipped:
        notes.append(f"{skipped} non-code entity change(s) (docs, JSON, TOML) listed but not impact-analysed")
    for ch in code_changes:
        try:
            impacts.append(graph_impact(repo, ch.name, file_path=ch.file_path, scan_files=scan_files))
        except GraphError as exc:
            failed += 1
            notes.append(f"impact analysis failed for {ch.name}: {exc}")
    analysis, partial_reasons = analysis_state(impacts, failed)
    entry_symbols = {m.entry_symbol for m in cfg.mappings}
    reached = [c for imp in impacts for c in reachable_entry_points(imp, entry_symbols)]
    reached_names = {c.name for c in reached}
    # [3] safe fallback: when analysis is partial, a missing edge must not read as "safe".
    mappings, fallback = select_mappings(cfg.mappings, reached_names, analysis, bool(code_changes))

    # [4] intent
    intent = None
    if mappings:
        m = mappings[0]
        intent = lookup_intent(repo, m.intent_file, m.intent_checkpoint, m.intent_query, use_entire)
    else:
        from ripple.intent import Intent
        intent = Intent("(no configured pipeline reached by this change)", "", "", None, "none")

    # [5] execute base and head over the same snapshot
    local_diffs = []
    databricks = None
    rows = load_snapshot(repo / cfg.snapshot.csv)
    for m in mappings:
        base_out = run_entry_point(repo, base, m.entry_file, m.entry_symbol, rows)
        head_out = run_entry_point(repo, head, m.entry_file, m.entry_symbol, rows)
        keys = {"clean_transactions": cfg.snapshot.key_clean, "daily_revenue": cfg.snapshot.key_daily}
        local_diffs.extend(compare_outputs(base_out, head_out, keys))
        # [6] Databricks comparison
        if backend == "databricks":
            run_id = f"{base}..{head}@{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
            try:
                ensure_tables(m.databricks_warehouse_id)
                publish_run(m.databricks_warehouse_id, run_id, rows, base_out, head_out)
                databricks = compare_run(m.databricks_warehouse_id, run_id)
                save_evidence(repo / "evidence" / "databricks" / "last_run.json", databricks)
            except DatabricksError as exc:
                notes.append(f"Databricks backend failed ({exc}); showing local comparison only. "
                             f"Cached evidence: evidence/databricks/last_run.json")

    warnings = list(diff.warnings) + [w for imp in impacts for w in imp.warnings]
    rc = cardmod.ReviewCard(base=base, head=head, intent=intent, changed=diff.changed, impacts=impacts,
                            reached_entry_points=reached, mappings=mappings, local_diffs=local_diffs,
                            databricks=databricks, graph_warnings=warnings, notes=notes,
                            analysis=analysis, partial_reasons=partial_reasons,
                            fallback_entry_points=fallback,
                            executed_entry_points=[m.entry_point for m in mappings])
    rc.verdict = cardmod.decide(rc)
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(cardmod.render_markdown(rc))
        out.with_suffix(".json").write_text(rc.to_json())
    return rc


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="ripple")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("review", help="review a code change for downstream data consequences")
    r.add_argument("--repo", default=".")
    r.add_argument("--base", default="main")
    r.add_argument("--head", default="HEAD")
    r.add_argument("--backend", choices=["local", "databricks"], default="local")
    r.add_argument("--out", default=None, help="write review card markdown (+ .json) here")
    r.add_argument("--no-entire-checkpoint", action="store_true", help="skip `entire checkpoint search`")
    a = p.parse_args(argv)
    try:
        rc = review(Path(a.repo).resolve(), a.base, a.head, a.backend, Path(a.out) if a.out else None,
                    use_entire=not a.no_entire_checkpoint)
    except GraphError as exc:
        print(f"ripple: graph error: {exc}", file=sys.stderr)
        return 2
    print(cardmod.render_markdown(rc))
    if rc.verdict.startswith(cardmod.BLOCK):
        return 1
    if rc.verdict.startswith(cardmod.NEEDS_VERIFICATION):
        return 3
    return 0
