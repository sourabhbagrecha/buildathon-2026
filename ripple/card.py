"""Review card: requirement, source locations, affected data products, reproducible comparison."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

from ripple.compare import TableDiff
from ripple.config import Mapping
from ripple.graph import Caller, ChangedSymbol, DiffResult, ImpactResult
from ripple.intent import Intent


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

    def to_dict(self) -> dict:
        d = asdict(self)
        for imp in d["impacts"]:
            imp.pop("raw", None)
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, default=str)


def decide(card: ReviewCard) -> str:
    """BLOCK if any output table changed and the intent is contradicted, PASS if nothing changed."""
    changed = any(t.rows_changed or t.only_in_base or t.only_in_head for t in card.local_diffs)
    if card.databricks and card.databricks.get("row_diff"):
        changed = changed or bool(card.databricks["row_diff"]["rows"])
    if not changed:
        return "PASS: outputs identical for base and head over the snapshot"
    return "BLOCK: downstream data changed meaning; review against the stated intent"


def render_markdown(card: ReviewCard) -> str:
    L: list[str] = []
    L.append(f"# Ripple review card: `{card.base}` -> `{card.head}`")
    L.append("")
    L.append(f"**Verdict:** {card.verdict}")
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
        L.append(f"- Changed {c.kind} `{c.name}` in `{c.file_path}:{c.line}` ({c.change_type}, "
                 f"graph dependents: {c.dependents_count})")
    for imp in card.impacts:
        L.append(f"- Impact of `{imp.symbol}` (completeness: {imp.completeness_level}):")
        for cl in imp.callers:
            via = f" via `{cl.via}`" if cl.via else ""
            L.append(f"  - depth {cl.depth}: `{cl.name}` in `{cl.file_path}:{cl.start_line}`{via}, "
                     f"call site line {cl.call_site_line} [CALLS, entire-graph]")
    if card.graph_warnings:
        L.append("- Graph warnings:")
        for w in card.graph_warnings:
            L.append(f"  - `{w.get('code')}`: {w.get('effect_on_semantic_completeness') or w.get('message', '')}")
    L.append("")
    L.append("## 3. Affected data products (source = configured, ripple.toml)")
    if not card.reached_entry_points:
        L.append("- No configured entry point is reachable from the changed symbols.")
    for m in card.mappings:
        L.append(f"- Entry point `{m.entry_point}` -> job `{m.databricks_job}`")
        L.append(f"  - Input: `{m.input_table}`; outputs: {', '.join('`' + t + '`' for t in m.output_tables)}")
        L.append(f"  - Data products: {', '.join(m.data_products)}")
    L.append("")
    L.append("## 4. Reproducible comparison (same input snapshot)")
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
        L.append("  - Reproduce: `python3 -m ripple review --base {0} --head {1} --backend databricks`".format(card.base, card.head))
    else:
        L.append("- Databricks comparison not run (local backend).")
    if card.notes:
        L.append("")
        L.append("## Notes")
        for n in card.notes:
            L.append(f"- {n}")
    return "\n".join(L) + "\n"
