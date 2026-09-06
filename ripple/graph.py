"""Entire Graph wrapper: changed symbols (semantic diff) and blast radius (impact).

Graph output is EVIDENCE, not an oracle. Everything returned here carries
``source = "entire-graph"`` and passes through the graph's own warnings,
partial_failures and completeness so the review card can show them.

Every relationship carries a tri-state evidence label:

* ``confirmed``          structural relation (CALLS) with a recorded call site;
* ``heuristic``          non-structural relation (data flow, co-change, sibling)
                         or a relation reported while the graph itself says its
                         analysis is partial;
* ``needs-verification`` a claim with no call site behind it, or a path that the
                         graph cannot see at all (dynamic dispatch, reflection,
                         generated code). Ripple scans source for such references
                         itself because the graph reports ``completeness_level =
                         ok`` with zero callers in that case: a silent miss.

When analysis is partial the graph must never be the only basis for PASS;
``ripple.cli.review`` executes the configured entry points anyway.
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

CONFIRMED = "confirmed"
HEURISTIC = "heuristic"
NEEDS_VERIFICATION = "needs-verification"

ANALYSIS_COMPLETE = "complete"
ANALYSIS_PARTIAL = "partial"

STRUCTURAL_RELATIONS = {"CALLS", "INHERITS", "IMPLEMENTS", "OVERRIDES"}
# Entity kinds whose change can alter pipeline behaviour. Markdown sections, JSON keys
# and TOML tables also show up in `entire graph diff` but are data, not code.
CODE_KINDS = {"function", "method", "class"}
DATA_LANGUAGES = {"JSON", "Markdown", "TOML", "YAML", "Git Ignore", "Text"}
# Warnings that do not reduce semantic completeness of the call graph.
BENIGN_WARNINGS = {"W_WORKTREE_SNAPSHOT"}
# Patterns a static graph cannot resolve. Any of these near the symbol name means
# the caller list may be incomplete even when the graph says completeness is ok.
DYNAMIC_CALLS = {"getattr": "getattr", "globals": "globals()", "vars": "vars()", "eval": "eval",
                 "exec": "exec", "__import__": "__import__"}
# Regex fallback for files that do not parse.
DYNAMIC_PATTERNS = (
    (r"\bgetattr\s*\(", "getattr"),
    (r"\bglobals\s*\(\)", "globals()"),
    (r"\bvars\s*\(", "vars()"),
    (r"\bimportlib\.", "importlib"),
    (r"\b__import__\s*\(", "__import__"),
    (r"\bsys\.modules\b", "sys.modules"),
    (r"\beval\s*\(", "eval"),
    (r"\bexec\s*\(", "exec"),
)


class GraphError(RuntimeError):
    pass


@dataclass
class DynamicReference:
    """A place where a changed symbol's NAME appears as data (string) or is reached via reflection."""
    file_path: str
    line: int
    text: str
    reason: str


@dataclass
class ChangedSymbol:
    name: str
    kind: str
    file_path: str
    change_type: str
    dependents_count: int
    line: int | None = None
    language: str = "?"

    @property
    def is_code(self) -> bool:
        return self.kind in CODE_KINDS and self.language not in DATA_LANGUAGES


@dataclass
class Caller:
    name: str
    file_path: str
    start_line: int | None
    depth: int
    via: str | None
    call_site_line: int | None
    relation: str = "CALLS"
    evidence: str = CONFIRMED
    evidence_reason: str = ""


@dataclass
class ImpactResult:
    symbol: str
    callers: list[Caller]
    warnings: list[dict]
    partial_failures: list[dict]
    completeness_level: str
    analysis: str = ANALYSIS_COMPLETE
    partial_reasons: list[str] = field(default_factory=list)
    dynamic_references: list[DynamicReference] = field(default_factory=list)
    raw: dict = field(repr=False, default_factory=dict)

    @property
    def is_partial(self) -> bool:
        return self.analysis == ANALYSIS_PARTIAL


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
                    language=f.get("language", "?"),
                )
            )
    return DiffResult(base=base, head=head, changed=changed, warnings=data.get("warnings", []) or [], raw=data)


def graph_partial_reasons(warnings: list[dict], partial_failures: list[dict], level: str) -> list[str]:
    """Reasons, from the graph's own signals, why its caller list may be incomplete."""
    reasons: list[str] = []
    if level != "ok":
        reasons.append(f"graph completeness_level is '{level}'")
    for pf in partial_failures:
        reasons.append(f"graph partial failure {pf.get('code', '?')} in {pf.get('file_path', '?')}: {pf.get('message', '')}".rstrip(": "))
    for w in warnings:
        if w.get("code") not in BENIGN_WARNINGS:
            reasons.append(f"graph warning {w.get('code', '?')}: {w.get('effect_on_semantic_completeness') or w.get('message', '')}")
    return reasons


def label_caller(entry: dict, graph_partial: bool) -> tuple[str, str]:
    """Tri-state label for one impact entry."""
    relation = entry.get("relation") or "?"
    cs = entry.get("call_site") or {}
    if relation not in STRUCTURAL_RELATIONS:
        return HEURISTIC, f"{relation} is not a structural call relation"
    if not cs.get("line"):
        return NEEDS_VERIFICATION, f"{relation} edge reported without a call site"
    if graph_partial:
        return HEURISTIC, "call site recorded, but the graph reports partial analysis for this query"
    return CONFIRMED, f"{relation} edge with call site {cs.get('file_path', '?')}:{cs.get('line')}"


def parse_impact(data: dict, symbol: str, dynamic_references: list[DynamicReference] | None = None) -> ImpactResult:
    warnings = data.get("warnings", []) or []
    partial_failures = data.get("partial_failures", []) or []
    level = ((data.get("stats") or {}).get("completeness_level")
             or (data.get("completeness_scope") or {}).get("level")
             or "unknown")
    reasons = graph_partial_reasons(warnings, partial_failures, level)
    graph_partial = bool(reasons)
    callers: list[Caller] = []
    for e in (data.get("callers") or {}).get("entries") or []:
        ep = e.get("endpoint", {})
        cs = e.get("call_site") or {}
        evidence, why = label_caller(e, graph_partial)
        callers.append(
            Caller(
                name=ep.get("name", "?"),
                file_path=ep.get("file_path", "?"),
                start_line=ep.get("start_line"),
                depth=int(e.get("depth", 1)),
                via=e.get("via"),
                call_site_line=cs.get("line"),
                relation=e.get("relation") or "?",
                evidence=evidence,
                evidence_reason=why,
            )
        )
    dyn = list(dynamic_references or [])
    for ref in dyn:
        reasons.append(f"dynamic reference to `{symbol}` at {ref.file_path}:{ref.line} ({ref.reason}); "
                       f"the graph cannot resolve this path")
    return ImpactResult(
        symbol=symbol,
        callers=callers,
        warnings=warnings,
        partial_failures=partial_failures,
        completeness_level=level,
        analysis=ANALYSIS_PARTIAL if reasons else ANALYSIS_COMPLETE,
        partial_reasons=reasons,
        dynamic_references=dyn,
        raw=data,
    )


def scan_dynamic_references(source: str, symbol: str, file_path: str) -> list[DynamicReference]:
    """Find places where ``symbol`` is referenced as DATA rather than as a call.

    Two signals, both cheap and explainable, and BOTH must be present in the file:
    1. the symbol name as a string constant (registry, config key, getattr target);
    2. a reflection/dispatch call (getattr, globals(), vars(), importlib, __import__,
       eval, exec) or a ``sys.modules`` lookup.
    Requiring both keeps dict keys that merely share a function's name (``{"run": ...}``)
    from tainting a review, while a registry + ``getattr`` pair is always reported.
    Uses the AST so docstrings and comments never count; falls back to a regex scan when
    the file does not parse (the graph would be partial for that file anyway).
    """
    lines = source.splitlines()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return _scan_dynamic_references_regex(lines, symbol, file_path)
    string_hits: list[int] = []
    dispatch_hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and node.value == symbol:
            string_hits.append(node.lineno)
        elif isinstance(node, ast.Call):
            fn = node.func
            label = None
            if isinstance(fn, ast.Name) and fn.id in DYNAMIC_CALLS:
                label = DYNAMIC_CALLS[fn.id]
            elif isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name) and fn.value.id == "importlib":
                label = "importlib"
            if label:
                dispatch_hits.append((node.lineno, label))
        elif (isinstance(node, ast.Attribute) and node.attr == "modules"
              and isinstance(node.value, ast.Name) and node.value.id == "sys"):
            dispatch_hits.append((node.lineno, "sys.modules"))
    if not string_hits or not dispatch_hits:
        return []
    refs = [DynamicReference(file_path, i, lines[i - 1].strip(), "symbol name used as a string literal")
            for i in sorted(set(string_hits))]
    refs += [DynamicReference(file_path, i, lines[i - 1].strip(), f"reflection/dynamic dispatch via {label}")
             for i, label in sorted(set(dispatch_hits))]
    return refs


def _scan_dynamic_references_regex(lines: list[str], symbol: str, file_path: str) -> list[DynamicReference]:
    string_ref = re.compile(r"[\"']" + re.escape(symbol) + r"[\"']")
    string_hits = [i for i, ln in enumerate(lines, start=1) if string_ref.search(ln.split("#", 1)[0])]
    dispatch_hits = []
    for i, ln in enumerate(lines, start=1):
        for pat, label in DYNAMIC_PATTERNS:
            if re.search(pat, ln.split("#", 1)[0]):
                dispatch_hits.append((i, label))
                break
    if not string_hits or not dispatch_hits:
        return []
    refs = [DynamicReference(file_path, i, lines[i - 1].strip(), "symbol name used as a string literal") for i in string_hits]
    refs += [DynamicReference(file_path, i, lines[i - 1].strip(), f"reflection/dynamic dispatch via {label}")
             for i, label in dispatch_hits]
    return refs


def graph_diff(repo: Path, base: str, head: str) -> DiffResult:
    data = _run(["entire", "graph", "diff", "--repo", str(repo), "--base", base, "--head", head, "--json"], repo)
    return parse_diff(data, base, head)


def graph_impact(repo: Path, symbol: str, file_path: str | None = None, depth: int = 2,
                 scan_files: list[str] | None = None) -> ImpactResult:
    cmd = ["entire", "graph", "impact", "--repo", str(repo), "--symbol", symbol,
           "--depth", str(depth), "--format", "json", "--profile", "full"]
    if file_path:
        cmd += ["--file", file_path]
    data = _run(cmd, repo)
    dyn: list[DynamicReference] = []
    for f in dict.fromkeys([file_path, *(scan_files or [])]):
        if not f:
            continue
        path = repo / f
        # Only source files can dispatch dynamically; JSON/TOML "symbols" are data keys.
        if path.is_file() and path.suffix == ".py":
            dyn.extend(scan_dynamic_references(path.read_text(), symbol, f))
    return parse_impact(data, symbol, dyn)


def reachable_entry_points(impact: ImpactResult, entry_symbols: set[str]) -> list[Caller]:
    """Callers (direct or transitive) whose name is a configured entry point, with evidence labels."""
    return [c for c in impact.callers if c.name in entry_symbols]


def analysis_state(impacts: list[ImpactResult], failed: int = 0) -> tuple[str, list[str]]:
    """Overall analysis state across all changed symbols; a failed impact query counts as partial."""
    reasons = list(dict.fromkeys(f"{imp.symbol}: {r}" for imp in impacts for r in imp.partial_reasons))
    if failed:
        reasons.append(f"{failed} impact quer{'y' if failed == 1 else 'ies'} failed")
    return (ANALYSIS_PARTIAL if reasons else ANALYSIS_COMPLETE), reasons
