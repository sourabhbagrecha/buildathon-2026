"""Row-level and aggregate comparison of base vs head outputs (pure Python)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RowDiff:
    key: str
    column: str
    base: object
    head: object


@dataclass
class TableDiff:
    table: str
    key: str
    rows_base: int
    rows_head: int
    rows_changed: int
    only_in_base: int
    only_in_head: int
    diffs: list[RowDiff] = field(default_factory=list)
    numeric_delta: dict[str, float] = field(default_factory=dict)  # column -> sum(head-base)


def _index(rows: list[dict], key: str) -> dict[str, dict]:
    return {str(r[key]): r for r in rows}


def compare_table(table: str, key: str, base: list[dict], head: list[dict], max_examples: int = 500) -> TableDiff:
    b, h = _index(base, key), _index(head, key)
    diffs: list[RowDiff] = []
    delta: dict[str, float] = {}
    changed = 0
    for k in sorted(set(b) & set(h)):
        rb, rh = b[k], h[k]
        row_changed = False
        for col in rb:
            vb, vh = rb.get(col), rh.get(col)
            if vb != vh:
                row_changed = True
                if isinstance(vb, (int, float)) and isinstance(vh, (int, float)):
                    delta[col] = round(delta.get(col, 0.0) + (vh - vb), 2)
                if len(diffs) < max_examples:
                    diffs.append(RowDiff(k, col, vb, vh))
        changed += row_changed
    return TableDiff(
        table=table, key=key, rows_base=len(b), rows_head=len(h), rows_changed=changed,
        only_in_base=len(set(b) - set(h)), only_in_head=len(set(h) - set(b)),
        diffs=diffs, numeric_delta=delta,
    )


def compare_outputs(base_out: dict, head_out: dict, keys: dict[str, str]) -> list[TableDiff]:
    return [compare_table(t, keys[t], base_out[t], head_out[t]) for t in base_out if t in keys]
