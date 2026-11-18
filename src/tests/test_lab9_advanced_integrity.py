"""M7 extra vectors for gate.integrity_check / slice_check (hand-built reports, no shape run).
Beyond the four public traps: an edited summary, relabelled slices, a failing row replaced by a copy
of a passing one, a removed slice, a blocking metric turned off."""
import copy

import pytest

pytestmark = pytest.mark.student

ITEMS, SEEDS = 4, (1, 2, 3)
ROWS = [{"item_id": f"E-{i:03d}", "seed": s, "pass_rate": True, "slices": ["money_movement"] if i < 2 else []}
        for i in range(ITEMS) for s in SEEDS]
SPEC = {
    "eval_set_version": "v2", "seeds": list(SEEDS),
    "metrics": [{"id": "pass_rate", "kind": "capability", "blocking": True,
                 "threshold": {"min": 0.8, "no_significant_drop": True}}],
    "slices": [{"name": "money_movement", "metric": "pass_rate", "min": 0.9, "no_significant_drop": True,
                "blocking": True}],
}


def report(rows=None, metrics=None):
    rows = copy.deepcopy(ROWS if rows is None else rows)
    ok = [bool(r["pass_rate"]) for r in rows]
    return {"manifest": {"eval_set_sha": "x", "items": ITEMS, "seeds": list(SEEDS)}, "rows": rows,
            "metrics": metrics or {"pass_rate": sum(ok) / len(ok)}, "evaluator_failures": []}


@pytest.fixture(scope="module")
def gate():
    from lab9 import gate

    return gate


def failing_report():
    rows = copy.deepcopy(ROWS)
    rows[0]["pass_rate"] = False
    return report(rows)


def test_honest_report_is_clean(gate):
    base = report()
    assert gate.integrity_check(base, base, SPEC, SPEC) == []
    assert gate.integrity_check(failing_report(), base, SPEC, SPEC) == []   # failing is the gate's job, not integrity's


def test_edited_summary_is_caught(gate):
    pr = failing_report()
    pr["metrics"]["pass_rate"] = 1.0           # rows say 11/12, summary says 1.0
    assert any("rows give" in p for p in gate.integrity_check(pr, report(), SPEC, SPEC))


def test_relabelled_slice_is_caught(gate):
    pr = failing_report()
    for r in pr["rows"]:
        r["slices"] = []
    assert any("slice tags" in p for p in gate.integrity_check(pr, report(), SPEC, SPEC))


def test_failing_row_replaced_by_a_copy_is_caught(gate):
    pr = failing_report()
    pr["rows"][0] = copy.deepcopy(pr["rows"][1])       # row count is still 12, but (item, seed) is duplicated
    pr["metrics"]["pass_rate"] = 1.0
    problems = gate.integrity_check(pr, report(), SPEC, SPEC)
    assert any("duplicated" in p for p in problems) and any("differs from the baseline" in p for p in problems)


def test_crashed_grader_row_is_caught(gate):
    pr = failing_report()
    pr["rows"][0]["pass_rate"] = None
    pr["metrics"]["pass_rate"] = 1.0
    assert any("no value" in p for p in gate.integrity_check(pr, report(), SPEC, SPEC))


@pytest.mark.parametrize("edit", [
    lambda s: s["slices"].clear(),                                            # slice removed
    lambda s: s["slices"][0].update(min=0.5),                                 # floor lowered
    lambda s: s["slices"][0].update(blocking=False),                          # no longer blocking
    lambda s: s["slices"][0].pop("no_significant_drop"),                      # drift check dropped
    lambda s: s["metrics"].clear(),                                           # metric removed
    lambda s: s["metrics"][0].update(blocking=False),
    lambda s: s["metrics"][0]["threshold"].update(min=0.1),
    lambda s: s["metrics"][0]["threshold"].pop("min"),                        # threshold deleted
    lambda s: s.update(seeds=[1]),                                            # fewer seeds
])
def test_loosened_spec_is_caught(gate, edit):
    loose = copy.deepcopy(SPEC)
    edit(loose)
    assert gate.integrity_check(report(), report(), loose, SPEC)


def test_stricter_spec_and_new_version_are_allowed(gate):
    strict = copy.deepcopy(SPEC)
    strict["metrics"][0]["threshold"]["min"] = 0.95
    strict["slices"][0]["min"] = 0.95
    assert gate.integrity_check(report(), report(), strict, SPEC) == []
    new_version = copy.deepcopy(SPEC)
    new_version["eval_set_version"] = "v3"
    new_version["metrics"][0]["threshold"]["min"] = 0.1       # a new eval set restarts the ratchet
    assert gate.integrity_check(report(), report(), new_version, SPEC) == []


def test_empty_slice_blocks_instead_of_passing(gate):
    pr = report([{**r, "slices": []} for r in ROWS])
    blocked, lines = gate.slice_check(pr, report(), SPEC)
    assert blocked == ["slice:money_movement/pass_rate"] and "MISSING" in lines[0]
