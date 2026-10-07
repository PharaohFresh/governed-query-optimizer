from __future__ import annotations

from collections import Counter
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import time


FIXTURES = Path(__file__).parent / "fixtures"
ALLOWED_TABLES = {"orders", "order_items"}
ALLOWED_FUNCTIONS = {"sum", "count", "avg", "min", "max", "coalesce", "abs", "round", "lower", "upper"}


class ValidationError(ValueError):
    pass


def digest(value) -> str:
    data = value if isinstance(value, bytes) else json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(data).hexdigest()


def fixture_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript((FIXTURES / "seed.sql").read_text(encoding="utf-8"))
    return conn


def _authorize(action, arg1, arg2, _database, _trigger):
    if action in {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_RECURSIVE}:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_READ and arg1 in ALLOWED_TABLES:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_FUNCTION and (arg2 or "").lower() in ALLOWED_FUNCTIONS:
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def _cell(value):
    if value is None:
        return ("null", None)
    if isinstance(value, int):
        return ("integer", value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValidationError("Non-finite result values are unsupported.")
        return ("float", value.hex())
    if isinstance(value, str):
        return ("text", value)
    raise ValidationError("Unsupported result value type.")


def read_query(conn: sqlite3.Connection, sql: str, *, max_rows: int = 10000, timeout: float = 2.0):
    if not isinstance(max_rows, int) or isinstance(max_rows, bool) or max_rows < 1:
        raise ValidationError("Row budget must be a positive integer.")
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not math.isfinite(timeout) or timeout <= 0:
        raise ValidationError("Query budgets must be positive.")
    started = time.monotonic()
    conn.set_authorizer(_authorize)
    conn.set_progress_handler(lambda: int(time.monotonic() - started >= timeout), 1000)
    try:
        cursor = conn.execute(sql)
        if cursor.description is None:
            raise ValidationError("Only read-only result queries are supported.")
        columns = tuple(column[0] for column in cursor.description)
        if len(set(columns)) != len(columns):
            raise ValidationError("Output column names must be unique.")
        rows = []
        while batch := cursor.fetchmany(min(256, max_rows + 1)):
            rows.extend(tuple(_cell(cell) for cell in row) for row in batch)
            if len(rows) > max_rows:
                raise ValidationError("Result exceeds the configured row budget.")
        return columns, Counter(rows)
    except sqlite3.Error as exc:
        raise ValidationError("Read-only query validation failed: " + str(exc)) from exc
    finally:
        conn.set_authorizer(None)
        conn.set_progress_handler(None, 0)


def compare_queries(original: str, candidate: str, *, connection=None, **budgets) -> dict:
    conn = connection or fixture_connection()
    own_connection = connection is None
    try:
        columns_a, rows_a = read_query(conn, original, **budgets)
        columns_b, rows_b = read_query(conn, candidate, **budgets)
        missing = rows_a - rows_b
        extra = rows_b - rows_a
        return {
            "equivalent": columns_a == columns_b and not missing and not extra,
            "column_names_match": columns_a == columns_b,
            "original_columns": list(columns_a), "candidate_columns": list(columns_b),
            "original_rows": sum(rows_a.values()), "candidate_rows": sum(rows_b.values()),
            "missing_row_occurrences": sum(missing.values()),
            "extra_row_occurrences": sum(extra.values()),
            "missing_examples": [{"row": row, "occurrences": count} for row, count in list(missing.items())[:5]],
            "extra_examples": [{"row": row, "occurrences": count} for row, count in list(extra.items())[:5]],
            "comparison": "ordered column contract; unordered typed row multiset; exact values and multiplicity",
        }
    finally:
        if own_connection:
            conn.close()


def cost_gate(original_bytes: int, candidate_bytes: int, minimum_reduction: float = 50.0) -> dict:
    if (isinstance(original_bytes, bool) or isinstance(candidate_bytes, bool)
            or not isinstance(original_bytes, int) or not isinstance(candidate_bytes, int)
            or original_bytes <= 0 or candidate_bytes < 0):
        raise ValidationError("Scan estimates require positive original and nonnegative candidate integer bytes.")
    if not math.isfinite(minimum_reduction) or not 0 <= minimum_reduction <= 100:
        raise ValidationError("Minimum scan reduction must be between zero and 100 percent.")
    reduction = 100 * (original_bytes - candidate_bytes) / original_bytes
    return {"passes": reduction >= minimum_reduction, "reduction_pct": round(reduction, 4),
            "minimum_reduction_pct": minimum_reduction, "original_bytes": original_bytes,
            "candidate_bytes": candidate_bytes, "evidence_type": "synthetic fixture estimate; no measured provider bill"}


def load_case(case_id: str) -> dict:
    catalog = json.loads((FIXTURES / "cases.json").read_text(encoding="utf-8"))
    try:
        return next(case for case in catalog if case["id"] == case_id)
    except StopIteration:
        raise ValidationError("Unknown demonstration case: " + case_id) from None


def evaluate_case(case_id: str) -> dict:
    case = load_case(case_id)
    original = (FIXTURES / case["original"]).read_text(encoding="utf-8")
    candidate = (FIXTURES / case["candidate"]).read_text(encoding="utf-8")
    cost = cost_gate(case["original_bytes"], case["candidate_bytes"])
    try:
        comparison = compare_queries(original, candidate)
        reason = "eligible for local staging" if comparison["equivalent"] and cost["passes"] else (
            "result contract changed" if not comparison["equivalent"] else "insufficient modeled scan reduction"
        )
    except ValidationError as exc:
        comparison = {"equivalent": False, "error": str(exc)}
        reason = "query rejected by the read-only evaluator"
    return {"case_id": case_id, "description": case["description"],
            "eligible": comparison["equivalent"] and cost["passes"], "reason": reason,
            "comparison": comparison, "cost": cost,
            "input_hashes": {"original_sql": digest(original.encode()), "candidate_sql": digest(candidate.encode()),
                             "seed_sql": digest((FIXTURES / "seed.sql").read_bytes()), "case_contract": digest(case)},
            "scope": "these frozen synthetic SQLite inputs; not proof of equivalence on unseen warehouse data"}


def make_plan(case_id: str) -> dict:
    evaluation = evaluate_case(case_id)
    if not evaluation["eligible"]:
        raise ValidationError("Blocked candidate: " + evaluation["reason"])
    case = load_case(case_id)
    return {"version": 1, "operation": "stage_local_sql", "case_id": case_id,
            "evaluation": evaluation, "candidate_sql": (FIXTURES / case["candidate"]).read_text(encoding="utf-8")}


def validate_plan(plan: dict) -> str:
    if not isinstance(plan, dict):
        raise ValidationError("Plan must be a JSON object.")
    if plan != make_plan(plan.get("case_id", "")):
        raise ValidationError("Plan or source changed; re-evaluate and obtain a new approval.")
    return digest(plan)


def approve_plan(plan: dict, actor: str) -> dict:
    if not actor.strip():
        raise ValidationError("An approver label is required.")
    return {"plan_sha256": validate_plan(plan), "approver": actor.strip(),
            "authorization_type": "explicit local-file attestation; identity is not authenticated"}


def stage_plan(plan: dict, approval: dict, output: Path) -> dict:
    plan_hash = validate_plan(plan)
    if not isinstance(approval, dict) or approval.get("plan_sha256") != plan_hash or not isinstance(approval.get("approver"), str) or not approval["approver"].strip():
        raise ValidationError("Approval does not cover this exact plan.")
    output.mkdir(parents=True, exist_ok=False)
    query_path = output / "accepted_query.sql"
    query_path.write_text(plan["candidate_sql"], encoding="utf-8", newline="\n")
    actual = digest(query_path.read_bytes())
    expected = digest(plan["candidate_sql"].encode())
    if actual != expected:
        raise ValidationError("Staged query readback failed.")
    receipt = {"status": "staged_and_read_back", "target": "local file only",
               "plan_sha256": plan_hash, "query_sha256": actual, "approval": approval,
               "fixture_equivalence": True, "cloud_deployment": False, "realized_savings": None}
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


def summarize_workloads(jobs: list[dict]) -> dict:
    seen, groups = {}, {}
    ignored_children = ignored_incomplete = duplicates = 0
    for job in jobs:
        job_id = job["job_id"]
        if job_id in seen:
            if seen[job_id] != job:
                raise ValidationError("Conflicting payloads for one job ID.")
            duplicates += 1
            continue
        seen[job_id] = job
        if job.get("parent_job_id"):
            ignored_children += 1
            continue
        if job.get("state") != "DONE" or job.get("error") is not None:
            ignored_incomplete += 1
            continue
        billed = job["billed_bytes"]
        if isinstance(billed, bool) or not isinstance(billed, int) or billed < 0:
            raise ValidationError("Job bytes must be nonnegative integers.")
        datetime.fromisoformat(job["created_at"])
        # A stable logical ID is supplied by the fixture. No claim of general SQL fingerprinting.
        group = groups.setdefault(job["workload_id"], {"jobs": 0, "billed_bytes": 0})
        group["jobs"] += 1
        group["billed_bytes"] += billed
    return {"workloads": groups, "duplicate_job_records_ignored": duplicates,
            "child_jobs_ignored": ignored_children, "failed_or_incomplete_jobs_ignored": ignored_incomplete,
            "annualized_savings": None, "evidence_type": "synthetic observed-window records"}
