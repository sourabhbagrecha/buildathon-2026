"""Intent lookup: the documented requirement behind a pipeline, tied to an Entire checkpoint."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Intent:
    requirement: str
    intent_file: str
    checkpoint_id: str
    checkpoint_snippet: str | None
    source: str  # "intent-file" | "intent-file+checkpoint"


def _requirement_line(text: str) -> str:
    for para in text.split("\n\n"):
        p = " ".join(para.split())
        if p.startswith("**Requirement:**"):
            return p.replace("**Requirement:**", "").strip()
    return " ".join(text.split())[:300]


def lookup_intent(repo: Path, intent_file: str, checkpoint_id: str, query: str, use_entire: bool = True) -> Intent:
    text = (repo / intent_file).read_text()
    snippet = None
    source = "intent-file"
    if use_entire:
        try:
            proc = subprocess.run(["entire", "checkpoint", "search", query], cwd=repo,
                                  capture_output=True, text=True, timeout=60)
            if proc.returncode == 0:
                data = json.loads(proc.stdout)
                for r in data.get("results", []):
                    d = r.get("data", {})
                    if d.get("matchedCheckpointId") == checkpoint_id or d.get("checkpointId") == checkpoint_id:
                        snip = (r.get("searchMeta") or {}).get("snippet", "")
                        idx = snip.lower().find("refunds must remain negative")
                        snippet = snip[max(0, idx - 80): idx + 200] if idx >= 0 else snip[:280]
                        source = "intent-file+checkpoint"
                        break
        except (OSError, json.JSONDecodeError, subprocess.TimeoutExpired):
            pass
    return Intent(requirement=_requirement_line(text), intent_file=intent_file,
                  checkpoint_id=checkpoint_id, checkpoint_snippet=snippet, source=source)
