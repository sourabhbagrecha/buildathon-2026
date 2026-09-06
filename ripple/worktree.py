"""Temporary git worktree so graph queries see the *head* revision, not the checked-out tree.

`entire graph` indexes the working tree. When ``--head`` names a revision that is not
checked out, impact and the dynamic-reference scan would describe the wrong code. Ripple
therefore materialises ``head`` in a detached worktree under a temporary directory, runs
the graph and scans against it, and removes it afterwards. Nothing is committed there.
"""

from __future__ import annotations

import contextlib
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass
class HeadTree:
    path: Path          # directory to pass as --repo to the graph and to read sources from
    sha: str            # resolved commit of head
    is_worktree: bool   # False when the checked-out tree already is head
    note: str           # one line for the review card


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.strip()[:300]}")
    return proc.stdout.strip()


def resolve(repo: Path, rev: str) -> str:
    return _git(repo, "rev-parse", "--verify", f"{rev}^{{commit}}")


def _tree_matches_checkout(repo: Path, sha: str) -> bool:
    """True when HEAD is `sha` and the tracked files are unmodified (so the checkout IS head)."""
    if _git(repo, "rev-parse", "HEAD") != sha:
        return False
    return _git(repo, "status", "--porcelain", "--untracked-files=no") == ""


@contextlib.contextmanager
def head_tree(repo: Path, head: str, enabled: bool = True):
    """Yield a HeadTree for ``head``; a temporary detached worktree unless the checkout already is head."""
    if head == "WORKTREE":
        yield HeadTree(repo, "WORKTREE", False, "graph analysed the working tree (head = WORKTREE)")
        return
    sha = resolve(repo, head)
    if not enabled or _tree_matches_checkout(repo, sha):
        why = "checked-out tree is head" if enabled else "--no-worktree given"
        yield HeadTree(repo, sha, False, f"graph analysed the checked-out tree at {sha[:12]} ({why})")
        return
    tmp = Path(tempfile.mkdtemp(prefix="ripple-head-"))
    wt = tmp / "head"
    try:
        _git(repo, "worktree", "add", "--detach", "--quiet", str(wt), sha)
        yield HeadTree(wt, sha, True, f"graph analysed `{head}` ({sha[:12]}) in a temporary worktree, not the checked-out tree")
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(wt)], cwd=repo, capture_output=True)
        shutil.rmtree(tmp, ignore_errors=True)
