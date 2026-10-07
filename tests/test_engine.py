import copy
import json
from pathlib import Path

import pytest

from governed_query_optimizer.engine import (
    FIXTURES, ValidationError, approve_plan, compare_queries, cost_gate, digest,
    evaluate_case, fixture_connection, make_plan, read_query, stage_plan, summarize_workloads,
)


@pytest.mark.parametrize("case_id,expected", [("preaggregate",True),("short_window",False),
 ("distinct_rows",False),("fill_null",False),("no_cost_benefit",False),("write_attempt",False)])
def test_case_verdicts(case_id, expected):
    assert evaluate_case(case_id)["eligible"] is expected


def test_multiset_catches_duplicates_a_set_would_miss():
    result = compare_queries("SELECT order_id,unit_price_cents FROM order_items",
                             "SELECT DISTINCT order_id,unit_price_cents FROM order_items")
    assert result["missing_row_occurrences"] == 1
    assert not result["equivalent"]


def test_column_contract_and_exact_type_are_preserved():
    assert not compare_queries("SELECT 1 AS count", "SELECT 1 AS total")["equivalent"]
    assert not compare_queries("SELECT 1 AS count", "SELECT 1.0 AS count")["equivalent"]


def test_row_order_is_not_part_of_unordered_result_contract():
    assert compare_queries("SELECT item_id FROM order_items ORDER BY item_id",
                           "SELECT item_id FROM order_items ORDER BY item_id DESC")["equivalent"]


@pytest.mark.parametrize("sql", ["DELETE FROM order_items", "UPDATE orders SET country='XX'",
 "DROP TABLE orders", "PRAGMA user_version=4", "ATTACH DATABASE ':memory:' AS other",
 "SELECT * FROM sqlite_master", "SELECT random() AS sample"])
def test_read_only_boundary_blocks_writes_metadata_and_nondeterminism(sql):
    conn = fixture_connection()
    with pytest.raises(ValidationError):
        read_query(conn, sql)
    assert conn.execute("SELECT COUNT(*) FROM order_items").fetchone()[0] == 8
    conn.close()


def test_multiple_statements_are_not_executed():
    conn = fixture_connection()
    with pytest.raises(ValidationError):
        read_query(conn,"SELECT 1; DELETE FROM order_items;")
    assert conn.execute("SELECT COUNT(*) FROM order_items").fetchone()[0] == 8


def test_row_budget_and_recursive_execution_budget():
    conn = fixture_connection()
    with pytest.raises(ValidationError,match="row budget"):
        read_query(conn,"SELECT * FROM order_items",max_rows=2)
    with pytest.raises(ValidationError):
        read_query(conn,"WITH RECURSIVE t(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM t) SELECT SUM(x) FROM t",timeout=0.001)


@pytest.mark.parametrize("budget", [float("nan"), float("inf"), -1, 0, True])
def test_non_finite_or_non_positive_timeout_is_rejected(budget):
    with pytest.raises(ValidationError):
        read_query(fixture_connection(), "SELECT 1 AS value", timeout=budget)


@pytest.mark.parametrize("budget", [True, 1.5, 0])
def test_row_budget_requires_positive_integer(budget):
    with pytest.raises(ValidationError):
        read_query(fixture_connection(), "SELECT 1 AS value", max_rows=budget)


def test_non_object_plans_and_approvals_fail_before_creating_output(tmp_path):
    with pytest.raises(ValidationError):
        stage_plan([], {}, tmp_path/"bad-plan")
    with pytest.raises(ValidationError):
        stage_plan(make_plan("preaggregate"), [], tmp_path/"bad-approval")
    assert not (tmp_path/"bad-plan").exists() and not (tmp_path/"bad-approval").exists()


@pytest.mark.parametrize("original,candidate", [(0,0),(-1,0),(100,-1),(True,0),(100,1.5)])
def test_invalid_cost_estimates_fail(original,candidate):
    with pytest.raises(ValidationError):
        cost_gate(original,candidate)


def test_cost_increase_is_not_a_saving():
    assert not cost_gate(100,200)["passes"]


def test_unsafe_candidate_cannot_be_planned():
    with pytest.raises(ValidationError):
        make_plan("short_window")


def test_staging_requires_exact_approved_plan(tmp_path):
    plan=make_plan("preaggregate")
    approval=approve_plan(plan,"demo-reviewer")
    with pytest.raises(ValidationError):
        stage_plan(plan,{},tmp_path/"blocked")
    modified=copy.deepcopy(plan);modified["candidate_sql"]+="\n-- changed after review"
    with pytest.raises(ValidationError):
        stage_plan(modified,approval,tmp_path/"changed")
    assert not (tmp_path/"blocked").exists()
    receipt=stage_plan(plan,approval,tmp_path/"approved")
    assert receipt["query_sha256"]==digest((tmp_path/"approved/accepted_query.sql").read_bytes())
    assert receipt["cloud_deployment"] is False
    with pytest.raises(FileExistsError):
        stage_plan(plan,approval,tmp_path/"approved")


def test_workload_history_does_not_double_count_parent_and_child_jobs():
    jobs=json.loads((FIXTURES/"jobs.json").read_text())
    result=summarize_workloads(jobs)
    assert result["workloads"]["daily-revenue"]["jobs"]==2
    assert result["workloads"]["daily-revenue"]["billed_bytes"]==536870912000
    assert result["duplicate_job_records_ignored"]==1
    assert result["child_jobs_ignored"]==1
    assert result["annualized_savings"] is None
    conflicting=copy.deepcopy(jobs[0]);conflicting["billed_bytes"]+=1
    with pytest.raises(ValidationError):
        summarize_workloads(jobs+[conflicting])
