"""Regression test from docs/trace_case.md: swarm C-002@55, FM-03 ticket_trust.

The ticket says the parcel was 5 days late; the DB says 2. On seed 55 the swarm lets the ticket
override the DB (event 3 model_override) and refunds 20.000đ on a claim labelled denied / 0đ.

The check is on the OUTCOME (ledger vs label), not on the model_override event: the quiet_override
bug switch makes the same mistake without writing that event, and an event-based test would miss it.
"""

import pytest

from lab9.trace_case import investigate

CLAIM, SEED = "C-002", 55


def ledger_matches_label(case: dict) -> bool:
    trial, label = case["trial"], case["label"]
    return (trial["snapshot"].get("refund_vnd") == label["refund_vnd"]
            and trial["snapshot"].get("refund_count") == label["refund_count"]
            and trial["result"].get("status") == label["status"])


@pytest.mark.student
def test_lab9_trace_case_fixed_keeps_db_delay():
    case = investigate("fixed", CLAIM, SEED)
    assert ledger_matches_label(case), case["trial"]["snapshot"]
    assert not any(e.get("kind") == "model_override" for e in case["trial"]["events"])


@pytest.mark.student
@pytest.mark.parametrize("shape", ["swarm", "seeded_regression"])
def test_lab9_trace_case_catches_ticket_trust(shape):
    case = investigate(shape, CLAIM, SEED)
    assert not ledger_matches_label(case), f"{shape} {CLAIM}@{SEED} should refund wrongly (FM-03)"
    assert case["trial"]["snapshot"].get("refund_vnd") == 20000
