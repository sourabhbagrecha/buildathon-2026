"""Databricks backend: store the snapshot and both outputs as Delta tables, compare via SQL.

Uses the Databricks SQL Statement Execution API through the ``databricks`` CLI
(profile from the CLI config; no secrets in this repo). All tables live in
``workspace.ripple``. Every run is tagged with ``run_id`` so evidence is reproducible.
"""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA = "workspace.ripple"


class DatabricksError(RuntimeError):
    pass


@dataclass
class SqlResult:
    statement_id: str
    columns: list[str]
    rows: list[list]
    statement: str = field(repr=False, default="")


def _api(method: str, path: str, body: dict | None = None, timeout: int = 120) -> dict:
    cmd = ["databricks", "api", method, path]
    if body is not None:
        cmd += ["--json", json.dumps(body)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise DatabricksError("databricks CLI not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise DatabricksError(f"databricks CLI timed out: {path}") from exc
    if proc.returncode != 0:
        raise DatabricksError(proc.stderr.strip()[:500] or proc.stdout[:500])
    return json.loads(proc.stdout or "{}")


def execute_sql(warehouse_id: str, statement: str, poll_seconds: float = 2.0, max_wait: int = 240) -> SqlResult:
    body = {"warehouse_id": warehouse_id, "statement": statement, "wait_timeout": "50s",
            "on_wait_timeout": "CONTINUE", "disposition": "INLINE", "format": "JSON_ARRAY"}
    resp = _api("post", "/api/2.0/sql/statements", body)
    sid = resp.get("statement_id", "")
    waited = 0.0
    while resp.get("status", {}).get("state") in ("PENDING", "RUNNING") and waited < max_wait:
        time.sleep(poll_seconds)
        waited += poll_seconds
        resp = _api("get", f"/api/2.0/sql/statements/{sid}")
    state = resp.get("status", {}).get("state")
    if state != "SUCCEEDED":
        err = resp.get("status", {}).get("error", {})
        raise DatabricksError(f"statement {sid} {state}: {err.get('message', '')[:400]}")
    cols = [c["name"] for c in (resp.get("manifest", {}).get("schema", {}).get("columns", []))]
    rows = resp.get("result", {}).get("data_array", []) or []
    return SqlResult(statement_id=sid, columns=cols, rows=rows, statement=statement)


def _lit(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return repr(v)
    return "'" + str(v).replace("'", "''") + "'"


def _values(rows: list[dict], cols: list[str], extra: dict | None = None) -> str:
    extra = extra or {}
    out = []
    for r in rows:
        vals = [_lit(extra[c]) if c in extra else _lit(r[c]) for c in cols]
        out.append("(" + ", ".join(vals) + ")")
    return ",\n".join(out)


DDL = {
    "raw_transactions": "run_id STRING, txn_id STRING, txn_date DATE, customer_id STRING, kind STRING, amount DOUBLE",
    "clean_transactions": "run_id STRING, version STRING, txn_id STRING, txn_date DATE, customer_id STRING, kind STRING, amount DOUBLE",
    "daily_revenue": "run_id STRING, version STRING, txn_date DATE, net_revenue DOUBLE, txn_count INT",
}


def ensure_tables(warehouse_id: str) -> list[str]:
    ids = [execute_sql(warehouse_id, f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}").statement_id]
    for t, cols in DDL.items():
        ids.append(execute_sql(warehouse_id, f"CREATE TABLE IF NOT EXISTS {SCHEMA}.{t} ({cols}) USING DELTA").statement_id)
    return ids


def publish_run(warehouse_id: str, run_id: str, raw: list[dict], base_out: dict, head_out: dict) -> list[str]:
    ids = []
    raw_cols = ["run_id", "txn_id", "txn_date", "customer_id", "kind", "amount"]
    ids.append(execute_sql(warehouse_id, f"DELETE FROM {SCHEMA}.raw_transactions WHERE run_id = {_lit(run_id)}").statement_id)
    ids.append(execute_sql(
        warehouse_id,
        f"INSERT INTO {SCHEMA}.raw_transactions ({', '.join(raw_cols)}) VALUES\n" + _values(raw, raw_cols, {"run_id": run_id}),
    ).statement_id)
    for table, cols in (
        ("clean_transactions", ["run_id", "version", "txn_id", "txn_date", "customer_id", "kind", "amount"]),
        ("daily_revenue", ["run_id", "version", "txn_date", "net_revenue", "txn_count"]),
    ):
        ids.append(execute_sql(warehouse_id, f"DELETE FROM {SCHEMA}.{table} WHERE run_id = {_lit(run_id)}").statement_id)
        for version, out in (("base", base_out), ("head", head_out)):
            ids.append(execute_sql(
                warehouse_id,
                f"INSERT INTO {SCHEMA}.{table} ({', '.join(cols)}) VALUES\n"
                + _values(out[table], cols, {"run_id": run_id, "version": version}),
            ).statement_id)
    return ids


ROW_DIFF_SQL = """
SELECT b.txn_id, b.kind, b.amount AS base_amount, h.amount AS head_amount,
       ROUND(h.amount - b.amount, 2) AS delta
FROM {schema}.clean_transactions b
JOIN {schema}.clean_transactions h
  ON b.txn_id = h.txn_id AND b.run_id = h.run_id
WHERE b.run_id = {run_id} AND b.version = 'base' AND h.version = 'head'
  AND NOT (b.amount <=> h.amount)
ORDER BY b.txn_id
""".strip()

AGG_DIFF_SQL = """
SELECT b.txn_date, b.net_revenue AS base_net_revenue, h.net_revenue AS head_net_revenue,
       ROUND(h.net_revenue - b.net_revenue, 2) AS delta
FROM {schema}.daily_revenue b
JOIN {schema}.daily_revenue h
  ON b.txn_date = h.txn_date AND b.run_id = h.run_id
WHERE b.run_id = {run_id} AND b.version = 'base' AND h.version = 'head'
  AND NOT (b.net_revenue <=> h.net_revenue)
ORDER BY b.txn_date
""".strip()

SUMMARY_SQL = """
SELECT
  (SELECT COUNT(*) FROM {schema}.clean_transactions WHERE run_id = {run_id} AND version = 'base') AS rows_base,
  (SELECT COUNT(*) FROM {schema}.clean_transactions WHERE run_id = {run_id} AND version = 'head') AS rows_head,
  (SELECT ROUND(SUM(net_revenue), 2) FROM {schema}.daily_revenue WHERE run_id = {run_id} AND version = 'base') AS total_base,
  (SELECT ROUND(SUM(net_revenue), 2) FROM {schema}.daily_revenue WHERE run_id = {run_id} AND version = 'head') AS total_head
""".strip()


def compare_run(warehouse_id: str, run_id: str) -> dict:
    fmt = {"schema": SCHEMA, "run_id": _lit(run_id)}
    row = execute_sql(warehouse_id, ROW_DIFF_SQL.format(**fmt))
    agg = execute_sql(warehouse_id, AGG_DIFF_SQL.format(**fmt))
    summ = execute_sql(warehouse_id, SUMMARY_SQL.format(**fmt))
    s = dict(zip(summ.columns, summ.rows[0])) if summ.rows else {}
    return {
        "backend": "databricks",
        "schema": SCHEMA,
        "run_id": run_id,
        "warehouse_id": warehouse_id,
        "statement_ids": {"row_diff": row.statement_id, "agg_diff": agg.statement_id, "summary": summ.statement_id},
        "sql": {"row_diff": row.statement, "agg_diff": agg.statement, "summary": summ.statement},
        "row_diff": {"columns": row.columns, "rows": row.rows},
        "agg_diff": {"columns": agg.columns, "rows": agg.rows},
        "summary": s,
    }


def save_evidence(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str))
