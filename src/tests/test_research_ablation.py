"""R2: isolate the reference swarm's use of ticket delay, without editing it."""

import json

from lab8.benchmark import run_benchmark
from lab8.config_loader import repo_path
from lab8.shapes import swarm_reference
from tests.conftest import CLAIMS, WORLD


def test_ticket_delay_ablation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    settings = {
        "world": WORLD,
        "claims": CLAIMS,
        "shapes": ["swarm"],
        "seeds": [11, 22, 33, 44, 55],
    }
    baseline = run_benchmark(**settings)
    # Only the shape's ticket-delay value is removed. MockLLM calls, including
    # its parse call, still run normally; tools, host and evaluator stay intact.
    with monkeypatch.context() as intervention:
        intervention.setattr(swarm_reference, "parse_delay_days", lambda ticket: None)
        ablated = run_benchmark(**settings)

    assert baseline["controlled_variables"] == ablated["controlled_variables"]
    before = {(row["claim_id"], row["seed"]): row for row in baseline["trials"]}
    after = {(row["claim_id"], row["seed"]): row for row in ablated["trials"]}
    assert before.keys() == after.keys()
    assert len(before) == 70
    changed = []
    for key, left in before.items():
        right = after[key]
        assert left["model_calls"] == right["model_calls"]
        if left["passed"] != right["passed"]:
            changed.append({
                "run_id": left["run_id"],
                "before_passed": left["passed"],
                "after_passed": right["passed"],
                "before_reason": left["reason"],
                "after_reason": right["reason"],
            })
        else:
            assert left == right
    assert changed == [{
        "run_id": "R-swarm-C-002-s55",
        "before_passed": False,
        "after_passed": True,
        "before_reason": "status resolved != denied",
        "after_reason": "ok",
    }]
    assert baseline["by_shape"]["swarm"]["successes"] == 69
    assert ablated["by_shape"]["swarm"]["successes"] == 70

    report = {
        "question": "R2",
        "intervention": "disable_shape_ticket_delay_only",
        "method": "parse_delay_days in the shape returns None; MockLLM and host unchanged",
        "comparison_scope": "pair run_id with baseline/ablated arm; public data only",
        "baseline": baseline,
        "ablated": ablated,
        "changed_trials": changed,
    }
    output = repo_path("reports", "research_ablation.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
