"""ripple CLI: `python3 -m ripple review --base main --head <rev> [--backend local|databricks] [--execute local|databricks]`."""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from ripple import card as cardmod
from ripple.compare import compare_outputs
from ripple.config import Mapping, load_config
from ripple.databricks_backend import (DatabricksError, compare_run, discover_lineage, ensure_tables,
                                       publish_outputs, publish_snapshot, save_evidence)
from ripple.execute import load_snapshot, run_entry_point, source_at
from ripple.graph import (ANALYSIS_PARTIAL, GraphError, analysis_state, graph_diff, graph_impact, reachable_entry_points,
                          scan_cross_file_references, scan_set)
from ripple.intent import lookup_intent
from ripple.worktree import head_tree


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


def review(repo: Path, base: str, head: str, backend: str, out: Path | None, use_entire: bool = True,
           execute: str = "local", use_worktree: bool = True, lineage: bool = True) -> cardmod.ReviewCard:
    cfg = load_config(repo)
    notes: list[str] = []
    if execute == "databricks":
        backend = "databricks"

    # [1] semantic diff between the two git revisions
    diff = graph_diff(repo, base, head)
    code_changes = [ch for ch in diff.changed if ch.is_code]
    skipped = len(diff.changed) - len(code_changes)
    if skipped:
        notes.append(f"{skipped} non-code entity change(s) (docs, JSON, TOML) listed but not impact-analysed")

    # [2] impact per changed symbol, computed against the HEAD tree (temporary worktree when the
    #     checkout is not head), plus Ripple's own same-file and cross-file dynamic-reference scans.
    impacts = []
    failed = 0
    entry_files = [m.entry_file for m in cfg.mappings]
    with head_tree(repo, head, enabled=use_worktree) as ht:
        changed_files = sorted({ch.file_path for ch in code_changes})
        files = scan_set(ht.path, changed_files, entry_files, cfg.scan.config_files, cfg.scan.extra_dirs)
        cross = scan_cross_file_references(files, {ch.name for ch in code_changes})
        for ch in code_changes:
            try:
                impacts.append(graph_impact(ht.path, ch.name, file_path=ch.file_path, scan_files=entry_files,
                                            extra_references=cross.get(ch.name)))
            except GraphError as exc:
                failed += 1
                notes.append(f"impact analysis failed for {ch.name}: {exc}")
        head_note = ht.note + f"; scanned {len(files)} file(s) for dynamic references"
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

    # [5] execute base and head over the same snapshot; [6] compare (locally and/or on Databricks)
    local_diffs = []
    databricks = None
    job_run = None
    lineage_info = None
    execution_errors: list[str] = []
    rows = load_snapshot(repo / cfg.snapshot.csv)
    keys = {"clean_transactions": cfg.snapshot.key_clean, "daily_revenue": cfg.snapshot.key_daily}
    for m in mappings:
        try:
            base_out = run_entry_point(repo, base, m.entry_file, m.entry_symbol, rows)
            head_out = run_entry_point(repo, head, m.entry_file, m.entry_symbol, rows)
        except Exception as exc:  # a revision that does not import/run is a finding, not a crash
            execution_errors.append(f"{m.entry_point}: {type(exc).__name__}: {str(exc)[:200]}")
            continue
        local_diffs.extend(compare_outputs(base_out, head_out, keys))
        if backend == "databricks":
            run_id = f"{base}..{head}@{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
            try:
                ensure_tables(m.databricks_warehouse_id)
                publish_snapshot(m.databricks_warehouse_id, run_id, rows)
                if execute == "databricks":
                    from ripple.databricks_job import execute_on_databricks
                    try:
                        job_run = execute_on_databricks(run_id, m.entry_file, m.entry_symbol,
                                                        source_at(repo, base, m.entry_file), source_at(repo, head, m.entry_file),
                                                        f"{m.databricks_job} {run_id}", repo / "evidence" / "databricks")
                    except DatabricksError as exc:
                        notes.append(f"Databricks job execution failed ({exc}); outputs of the local execution "
                                     f"were published instead")
                        publish_outputs(m.databricks_warehouse_id, run_id, base_out, head_out)
                else:
                    publish_outputs(m.databricks_warehouse_id, run_id, base_out, head_out)
                databricks = compare_run(m.databricks_warehouse_id, run_id)
                if job_run:
                    databricks["job_run"] = job_run
                save_evidence(repo / "evidence" / "databricks" / "last_run.json", databricks)
                if lineage:
                    lineage_info = discover_lineage(m.databricks_warehouse_id, [m.input_table, *m.output_tables])
            except DatabricksError as exc:
                notes.append(f"Databricks backend failed ({exc}); showing local comparison only. "
                             f"Cached evidence: evidence/databricks/last_run.json")

    warnings = list(diff.warnings) + [w for imp in impacts for w in imp.warnings]
    rc = cardmod.ReviewCard(base=base, head=head, intent=intent, changed=diff.changed, impacts=impacts,
                            reached_entry_points=reached, mappings=mappings, local_diffs=local_diffs,
                            databricks=databricks, graph_warnings=warnings, notes=notes,
                            analysis=analysis, partial_reasons=partial_reasons,
                            fallback_entry_points=fallback,
                            executed_entry_points=[m.entry_point for m in mappings],
                            execution_mode="databricks-job" if job_run else "local",
                            job_run=job_run, execution_errors=execution_errors,
                            head_tree_note=head_note, lineage=lineage_info)
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
    r.add_argument("--backend", choices=["local", "databricks"], default="local",
                   help="where the row/aggregate comparison is computed")
    r.add_argument("--execute", choices=["local", "databricks"], default="local",
                   help="where the two pipeline versions run: locally from git revisions, or as a serverless "
                        "Databricks job over the Delta snapshot (implies --backend databricks)")
    r.add_argument("--out", default=None, help="write review card markdown (+ .json) here")
    r.add_argument("--no-entire-checkpoint", action="store_true", help="skip `entire checkpoint search`")
    r.add_argument("--no-worktree", action="store_true",
                   help="query the graph against the checked-out tree instead of a temporary worktree at --head")
    r.add_argument("--no-lineage", action="store_true", help="skip the Unity Catalog lineage lookup")
    a = p.parse_args(argv)
    try:
        rc = review(Path(a.repo).resolve(), a.base, a.head, a.backend, Path(a.out) if a.out else None,
                    use_entire=not a.no_entire_checkpoint, execute=a.execute,
                    use_worktree=not a.no_worktree, lineage=not a.no_lineage)
    except GraphError as exc:
        print(f"ripple: graph error: {exc}", file=sys.stderr)
        return 2
    print(cardmod.render_markdown(rc))
    if rc.verdict.startswith(cardmod.BLOCK):
        return 1
    if rc.verdict.startswith(cardmod.NEEDS_VERIFICATION):
        return 3
    return 0
