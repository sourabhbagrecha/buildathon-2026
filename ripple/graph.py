"""Entire Graph wrapper: changed symbols (semantic diff) and blast radius (impact).

Graph output is EVIDENCE, not an oracle. Everything returned here carries
``source = "entire-graph"`` and passes through the graph's own warnings,
partial_failures and completeness so the review card can show them.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


class GraphError(RuntimeError):
    pass


@dataclass
class ChangedSymbol:
    name: str
    kind: str
    file_path: str
    change_type: str
    dependents_count: int
    line: int | None = None


@dataclass
class Caller:
    name: str
    file_path: str
    start_line: int | None
    depth: int
    via: str | None
    call_site_line: int | None


@dataclass
class ImpactResult:
    symbol: str
    callers: list[Caller]
    warnings: list[dict]
    partial_failures: list[dict]
    completeness_level: str
    raw: dict = field(repr=False, default_factory=dict)


@dataclass
class DiffResult:
    base: str
    head: str
    changed: list[ChangedSymbol]
    warnings: list[dict]
    raw: dict = field(repr=False, default_factory=dict)


def _run(cmd: list[str], cwd: Path) -> dict:
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=180)
    except FileNotFoundError as exc:
        raise GraphError(f"entire CLI not found: {exc}") from exc
    if proc.returncode != 0:
        raise GraphError(f"{' '.join(cmd)} failed: {proc.stderr.strip()[:500]}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise GraphError(f"non-JSON graph output: {proc.stdout[:200]}") from exc


def parse_diff(data: dict, base: str, head: str) -> DiffResult:
    changed: list[ChangedSymbol] = []
    for f in data.get("files") or []:
        for ch in f.get("changes") or []:
            changed.append(
                ChangedSymbol(
                    name=ch.get("name", "?"),
                    kind=ch.get("kind", "?"),
                    file_path=f.get("path", "?"),
                    change_type=ch.get("type", "?"),
                    dependents_count=int(ch.get("dependents_count", 0) or 0),
                    line=ch.get("after_start_line") or ch.get("before_start_line"),
                )
            )
    return DiffResult(base=base, head=head, changed=changed, warnings=data.get("warnings", []) or [], raw=data)


def parse_impact(data: dict, symbol: str) -> ImpactResult:
    callers: list[Caller] = []
    for e in (data.get("callers") or {}).get("entries") or []:
        ep = e.get("endpoint", {})
        cs = e.get("call_site") or {}
        callers.append(
            Caller(
                name=ep.get("name", "?"),
                file_path=ep.get("file_path", "?"),
                start_line=ep.get("start_line"),
                depth=int(e.get("depth", 1)),
                via=e.get("via"),
                call_site_line=cs.get("line"),
            )
        )
    level = ((data.get("stats") or {}).get("completeness_level")
             or (data.get("completeness_scope") or {}).get("level")
             or "unknown")
    return ImpactResult(
        symbol=symbol,
        callers=callers,
        warnings=data.get("warnings", []) or [],
        partial_failures=data.get("partial_failures", []) or [],
        completeness_level=level,
        raw=data,
    )


def graph_diff(repo: Path, base: str, head: str) -> DiffResult:
    data = _run(["entire", "graph", "diff", "--repo", str(repo), "--base", base, "--head", head, "--json"], repo)
    return parse_diff(data, base, head)


def graph_impact(repo: Path, symbol: str, file_path: str | None = None, depth: int = 2) -> ImpactResult:
    cmd = ["entire", "graph", "impact", "--repo", str(repo), "--symbol", symbol,
           "--depth", str(depth), "--format", "json", "--profile", "full"]
    if file_path:
        cmd += ["--file", file_path]
    data = _run(cmd, repo)
    return parse_impact(data, symbol)


def reachable_entry_points(impact: ImpactResult, entry_symbols: set[str]) -> list[Caller]:
    """Callers (direct or transitive) whose name is a configured entry point."""
    return [c for c in impact.callers if c.name in entry_symbols]
