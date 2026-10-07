import json

from governed_query_optimizer.cli import main


def test_demo_then_approval_and_staging_flow(tmp_path):
    output=tmp_path/"demo"
    assert main(["demo","--output",str(output)])==0
    report=json.loads((output/"report.json").read_text())
    assert sum(x["eligible"] for x in report["evaluations"])==1
    plan=output/"safe_plan.json";approval=tmp_path/"approval.json";stage=tmp_path/"stage"
    assert main(["stage","--plan",str(plan),"--approval",str(approval),"--output",str(stage)])==1
    assert not stage.exists()
    assert main(["approve","--plan",str(plan),"--actor","demo-reviewer","--output",str(approval)])==0
    assert main(["stage","--plan",str(plan),"--approval",str(approval),"--output",str(stage)])==0


def test_blocked_case_has_nonzero_exit():
    assert main(["evaluate","short_window"])==1
