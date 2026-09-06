"""Execute a pipeline entry point at a given git revision over the snapshot (local backend)."""

from __future__ import annotations

import csv
import subprocess
import types
from pathlib import Path

WORKTREE = "WORKTREE"


def load_snapshot(csv_path: Path) -> list[dict]:
    with csv_path.open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        r["amount"] = float(r["amount"])
    return rows


def source_at(repo: Path, rev: str, file_path: str) -> str:
    if rev == WORKTREE:
        return (repo / file_path).read_text()
    proc = subprocess.run(["git", "show", f"{rev}:{file_path}"], cwd=repo, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"git show {rev}:{file_path} failed: {proc.stderr.strip()}")
    return proc.stdout


def load_module_from_source(source: str, name: str) -> types.ModuleType:
    mod = types.ModuleType(name)
    exec(compile(source, f"<{name}>", "exec"), mod.__dict__)
    return mod


def run_entry_point(repo: Path, rev: str, entry_file: str, entry_symbol: str, rows: list[dict]) -> dict:
    src = source_at(repo, rev, entry_file)
    mod = load_module_from_source(src, f"ripple_exec_{rev.replace('/', '_')}")
    fn = getattr(mod, entry_symbol)
    # Deep-copy rows so the two executions cannot influence each other.
    return fn([dict(r) for r in rows])
