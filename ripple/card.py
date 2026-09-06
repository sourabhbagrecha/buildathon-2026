"""Review card: requirement, source locations, affected data products, reproducible comparison."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

from ripple.compare import TableDiff
from ripple.config import Mapping
from ripple.graph import ANALYSIS_COMPLETE, ANALYSIS_PARTIAL, Caller, ChangedSymbol, DiffResult, ImpactResult
from ripple.intent import Intent

PASS = "PASS"
BLOCK = "BLOCK"
NEEDS_VERIFICATION = "NEEDS-VERIFICATION"


@dataclass
class ReviewCard:
    base: str
    head: str
    intent: Intent
    changed: list[ChangedSymbol]
    impacts: list[ImpactResult]
    reached_entry_points: list[Caller]
    mappings: list[Mapping]
    local_diffs: list[TableDiff]
    databricks: dict | None
    graph_warnings: list[dict] = field(default_factory=list)
    verdict: str = ""
    notes: list[str] = field(default_factory=list)
    # Curveball: tri-state analysis state. "complete" only when every relationship that
    # led to the verdict is confirmed; "partial" when the graph (or Ripple's own dynamic-
    # reference scan) says callers may be missing. Partial analysis never yields PASS on
    # graph evidence alone; the configured entry points are executed as the fallback.
    analysis: str = ANALYSIS_COMPLETE
    partial_reasons: list[str] = field(default_factory=list)
    fallback_entry_points: list[str] = field(default_factory=list)
    executed_entry_points: list[str] = field(default_factory=list)
    # Where the two versions ran: "local" (git revision -> exec) or "databricks-job" (serverless
    # one-time run over the Delta snapshot). ``job_run`` holds run id, URL and state.
    execution_mode: str = "local"
    job_run: dict | None = None
    execution_errors: list[str] = field(default_factory=list)
    # How the graph saw `head`: a temporary worktree at head, or the checked-out tree.
    head_tree_note: str = ""
    # Unity Catalog lineage for the configured tables (source = unity-catalog-lineage, observed).
    lineage: dict | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        for imp in d["impacts"]:
            imp.pop("raw", None)
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, default=str)


def decide(card: ReviewCard) -> str:
    """Verdict.

    BLOCK               an output table changed for the same input snapshot.
    PASS                execution of every relevant entry point produced identical outputs, or
                        the graph analysis is complete and reaches no configured entry point.
    NEEDS-VERIFICATION  analysis is partial and no execution backed the claim; the graph
                        alone is never enough for PASS in that state.
    """
    changed = any(t.rows_changed or t.only_in_base or t.only_in_head for t in card.local_diffs)
    if card.databricks and card.databricks.get("row_diff"):
        changed = changed or bool(card.databricks["row_diff"]["rows"])
    if changed:
        return f"{BLOCK}: downstream data changed meaning; review against the stated intent"
    executed = bool(card.local_diffs) or bool(card.databricks)
    if card.execution_errors and not executed:
        return (f"{NEEDS_VERIFICATION}: execution of base or head failed ({card.execution_errors[0][:120]}); "
                f"no comparison backs this change")
    if card.analysis == ANALYSIS_PARTIAL:
        if executed:
            return (f"{PASS}: outputs identical for base and head over the snapshot "
                    f"(verified by execution; graph analysis partial, see banner)")
        return (f"{NEEDS_VERIFICATION}: graph analysis is partial and no entry point was executed; "
                f"run the configured entry points before trusting this change")
    if executed:
        return f"{PASS}: outputs identical for base and head over the snapshot"
    return f"{PASS}: no configured entry point reachable from the change (graph analysis complete, all relations confirmed)"


def _evidence_summary(card: ReviewCard) -> dict[str, int]:
    counts = {"confirmed": 0, "heuristic": 0, "needs-verification": 0}
    for imp in card.impacts:
        for c in imp.callers:
            counts[c.evidence] = counts.get(c.evidence, 0) + 1
    return counts


def render_markdown(card: ReviewCard) -> str:
    L: list[str] = []
    L.append(f"# Ripple review card: `{card.base}` -> `{card.head}`")
    L.append("")
    L.append(f"**Verdict:** {card.verdict}")
    L.append("")
    if card.analysis == ANALYSIS_PARTIAL:
        L.append("> **PARTIAL ANALYSIS.** The call graph may be missing callers of the changed code")
        L.append("> (dynamic dispatch, reflection, generated code, or a degraded graph run).")
        L.append("> Graph relationships below are labelled per edge; nothing here is PASS on graph evidence alone.")
        for r in card.partial_reasons:
            L.append(f"> - {r}")
        if card.fallback_entry_points:
            L.append(f"> - Fallback: executed configured entry point(s) {', '.join('`' + e + '`' for e in card.fallback_entry_points)} "
                     f"even though the graph did not reach them.")
        L.append("")
    ev = _evidence_summary(card)
    L.append(f"**Evidence:** analysis `{card.analysis}`; graph relations: {ev['confirmed']} confirmed, "
             f"{ev['heuristic']} heuristic, {ev['needs-verification']} needs-verification; "
             f"execution `{card.execution_mode}`")
    if card.head_tree_note:
        L.append(f"- {card.head_tree_note}")
    L.append("")
    L.append("## 1. Original requirement (intent)")
    if card.intent.source == "none":
        L.append(f"- {card.intent.requirement}")
    else:
        L.append(f"- Requirement: {card.intent.requirement}")
        L.append(f"- Source: `{card.intent.intent_file}`, Entire checkpoint `{card.intent.checkpoint_id}` "
                 f"(`entire checkpoint explain {card.intent.checkpoint_id}`) [{card.intent.source}]")
    if card.intent.checkpoint_snippet:
        L.append(f"- Checkpoint excerpt: \"...{card.intent.checkpoint_snippet.strip()}...\"")
    L.append("")
    L.append("## 2. Source locations (Entire Graph, source = entire-graph)")
    if not card.changed:
        L.append("- No entity-level changes reported by `entire graph diff`.")
    for c in card.changed:
        if not c.is_code:
            continue
        L.append(f"- Changed {c.kind} `{c.name}` in `{c.file_path}:{c.line}` ({c.change_type}, "
                 f"graph dependents: {c.dependents_count})")
    non_code = [c for c in card.changed if not c.is_code]
    if non_code:
        L.append(f"- {len(non_code)} non-code entity change(s) in "
                 f"{', '.join('`' + f + '`' for f in sorted({c.file_path for c in non_code}))} (not impact-analysed)")
    for imp in card.impacts:
        L.append(f"- Impact of `{imp.symbol}` (graph completeness: {imp.completeness_level}; analysis: {imp.analysis}):")
        if not imp.callers:
            L.append("  - graph reports no callers"
                     + (" **but analysis is partial: absence of callers is not evidence of safety**" if imp.is_partial else ""))
        for cl in imp.callers:
            via = f" via `{cl.via}`" if cl.via else ""
            L.append(f"  - depth {cl.depth}: `{cl.name}` in `{cl.file_path}:{cl.start_line}`{via}, "
                     f"call site line {cl.call_site_line} [{cl.relation}, entire-graph] **{cl.evidence}** ({cl.evidence_reason})")
        for ref in imp.dynamic_references:
            L.append(f"  - dynamic reference `{ref.file_path}:{ref.line}` `{ref.text}` [{ref.reason}, ripple-scan] "
                     f"**needs-verification**")
    if card.graph_warnings:
        L.append("- Graph warnings:")
        for w in card.graph_warnings:
            L.append(f"  - `{w.get('code')}`: {w.get('effect_on_semantic_completeness') or w.get('message', '')}")
    L.append("")
    L.append("## 3. Affected data products (source = configured, ripple.toml)")
    if not card.reached_entry_points:
        L.append("- No configured entry point is reachable from the changed symbols according to the graph"
                 + (" (analysis partial: executed as fallback)." if card.fallback_entry_points else "."))
    for m in card.mappings:
        how = ("fallback (graph did not reach it)" if m.entry_point in card.fallback_entry_points
               else "reached: " + ", ".join(sorted({c.evidence for c in card.reached_entry_points if c.name == m.entry_symbol}) or ["configured"]))
        L.append(f"- Entry point `{m.entry_point}` -> job `{m.databricks_job}` [{how}]")
        L.append(f"  - Input: `{m.input_table}`; outputs: {', '.join('`' + t + '`' for t in m.output_tables)}")
        L.append(f"  - Data products: {', '.join(m.data_products)}")
    if card.lineage is not None:
        lin = card.lineage
        if not lin.get("available"):
            L.append(f"- Unity Catalog lineage (source = unity-catalog-lineage): unavailable ({lin.get('error', '?')}); "
                     f"configured mappings only")
        else:
            L.append(f"- Unity Catalog lineage (source = unity-catalog-lineage, **observed** over the last "
                     f"{lin.get('days', '?')} days, statement `{lin.get('statement_id', '?')}`):")
            for t in lin.get("upstream_tables", []):
                L.append(f"  - upstream: `{t}` -> configured tables")
            for t in lin.get("downstream_tables", []):
                L.append(f"  - downstream table: configured tables -> `{t}` **confirmed** (observed write)")
            for r in lin.get("readers", []):
                L.append(f"  - downstream reader: `{r}` **confirmed** (observed read)")
            flows = [e for e in lin.get("edges", []) if e.get("source") and e.get("target")]
            for e in flows[:6]:
                L.append(f"  - flow `{e['source']}` -> `{e['target']}` (last seen {e.get('last_seen')}, {e.get('events')} event(s))")
            if not (lin.get("upstream_tables") or lin.get("downstream_tables") or lin.get("readers") or flows):
                L.append("  - no table-to-table flows or named readers observed; only ad-hoc reads/writes. "
                         "Absence of lineage is not evidence of no consumers.")
            L.append("  - Unity Catalog writes lineage asynchronously (observed lag: tens of minutes); events from this run appear on a later review. "
                     "A job that collects rows to the driver records reads and writes as separate events, not one flow.")
    L.append("")
    L.append("## 4. Reproducible comparison (same input snapshot)")
    if card.job_run:
        jr = card.job_run
        L.append(f"- Both versions executed **as a Databricks job** (serverless one-time run `{jr.get('run_id')}`, "
                 f"{jr.get('result_state')}, {jr.get('duration_s')} s): {jr.get('run_page_url')}")
        L.append(f"  - script: `{jr.get('python_file')}` (local copy `{jr.get('script_local', '?')}`); "
                 f"reads `raw_transactions`, writes `clean_transactions` and `daily_revenue` for `version = base|head`")
    for err in card.execution_errors:
        L.append(f"- **Execution error:** {err}")
    for t in card.local_diffs:
        L.append(f"- `{t.table}` (key `{t.key}`): {t.rows_changed} of {t.rows_base} rows changed"
                 f"{', numeric delta ' + json.dumps(t.numeric_delta) if t.numeric_delta else ''}"
                 f" [local execution of base and head]")
        for d in t.diffs[:5]:
            L.append(f"  - {t.key}={d.key} {d.column}: {d.base} -> {d.head}")
        if len(t.diffs) > 5:
            L.append(f"  - ... {len(t.diffs) - 5} more")
    if card.databricks:
        db = card.databricks
        L.append(f"- Databricks (`{db['schema']}`, run_id `{db['run_id']}`, warehouse `{db['warehouse_id']}`):")
        s = db.get("summary", {})
        L.append(f"  - clean_transactions rows: base {s.get('rows_base')}, head {s.get('rows_head')}; "
                 f"rows differing: {len(db['row_diff']['rows'])}")
        L.append(f"  - total net revenue: base {s.get('total_base')} -> head {s.get('total_head')}")
        for r in db["agg_diff"]["rows"][:14]:
            L.append(f"  - {r[0]}: {r[1]} -> {r[2]} (delta {r[3]})")
        L.append(f"  - SQL statement ids: {json.dumps(db['statement_ids'])}")
        L.append("  - Reproduce: `python3 -m ripple review --base {0} --head {1} --backend databricks{2}`".format(
            card.base, card.head, " --execute databricks" if card.job_run else ""))
    else:
        L.append("- Databricks comparison not run (local backend).")
    if card.notes:
        L.append("")
        L.append("## Notes")
        for n in card.notes:
            L.append(f"- {n}")
    return "\n".join(L) + "\n"
