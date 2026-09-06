"""Load ripple.toml. Every mapping here is CONFIGURED (explicit), never discovered."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Mapping:
    source: str
    entry_point: str            # "pipeline.transactions:run"
    entry_file: str
    databricks_job: str
    databricks_warehouse_id: str
    input_table: str
    output_tables: list[str]
    data_products: list[str]
    intent_file: str
    intent_checkpoint: str
    intent_query: str

    @property
    def entry_symbol(self) -> str:
        return self.entry_point.split(":", 1)[1]


@dataclass
class Snapshot:
    csv: str
    key_clean: str
    key_daily: str


@dataclass
class Config:
    repo_root: Path
    mappings: list[Mapping] = field(default_factory=list)
    snapshot: Snapshot | None = None


def load_config(repo_root: str | Path, path: str = "ripple.toml") -> Config:
    root = Path(repo_root)
    with (root / path).open("rb") as fh:
        raw = tomllib.load(fh)
    mappings = [Mapping(**m) for m in raw.get("mapping", [])]
    snap = Snapshot(**raw["snapshot"]) if "snapshot" in raw else None
    return Config(repo_root=root, mappings=mappings, snapshot=snap)
