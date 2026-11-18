"""Vai 4 — ledger/policy/crash trên ba shape nhóm viết.

Bổ sung cho ma trận public: crash ở từng điểm rồi resume, approval hết hạn,
approval mượn của claim khác, và quét secret/PII trong trace + kết quả.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

from lab8.db import connect
from lab8.durability import InjectedCrash, committed_audit_count
from tests.conftest import BY_ID

SHAPES = ["workflow", "single", "orchestrator"]
CRASH_POINTS = ["before_effect", "after_effect_before_checkpoint", "after_checkpoint"]


def _run(shape: str):
    return importlib.import_module(f"lab8.shapes.{shape}").run_claim


def _ledger_rows(store: Path, claim_id: str) -> list[dict]:
    conn = connect(store)
    rows = [dict(r) for r in conn.execute("SELECT * FROM refund_ledger WHERE claim_id = ?", (claim_id,))]
    conn.close()
    return rows


def _audit_count(store: Path, claim_id: str, event_type: str) -> int:
    conn = connect(store)
    n = conn.execute(
        "SELECT COUNT(*) FROM audit_events WHERE claim_id = ? AND event_type = ?",
        (claim_id, event_type),
    ).fetchone()[0]
    conn.close()
    return int(n)


@pytest.mark.student
@pytest.mark.parametrize("point", CRASH_POINTS)
@pytest.mark.parametrize("shape", SHAPES)
def test_crash_then_resume_pays_exactly_once(public_db, shape, point):
    run_claim = _run(shape)
    with pytest.raises(InjectedCrash):
        run_claim("C-001", seed=11, store_path=str(public_db), crash_at=point)
    result = run_claim("C-001", seed=11, store_path=str(public_db))
    # Resume twice more: still a single refund.
    run_claim("C-001", seed=22, store_path=str(public_db))

    rows = _ledger_rows(public_db, "C-001")
    conn = connect(public_db)
    audits = committed_audit_count(conn, "C-001")
    conn.close()
    assert result.status == "resolved"
    assert len(rows) == 1
    assert int(rows[0]["amount_vnd"]) == 35000
    assert audits == 1


@pytest.mark.student
@pytest.mark.parametrize("shape", SHAPES)
def test_expired_approval_is_denied_by_host(public_db, shape):
    result = _run(shape)("C-007", seed=11, store_path=str(public_db))
    assert result.status == "denied"
    assert result.proposal_amount == 35000  # full quote, host refused it
    assert result.refund_effects == []
    assert _ledger_rows(public_db, "C-007") == []
    assert _audit_count(public_db, "C-007", "policy_denied") >= 1


@pytest.mark.student
@pytest.mark.parametrize("shape", SHAPES)
def test_approval_borrowed_from_another_claim_is_blocked(public_db, shape):
    conn = connect(public_db)
    # C-001 now points at C-003's approval (150000 VND): must not pay.
    conn.execute("UPDATE claims SET approval_id = 'A-003' WHERE claim_id = 'C-001'")
    conn.commit()
    conn.close()
    result = _run(shape)("C-001", seed=11, store_path=str(public_db))
    assert result.status == "denied"
    assert result.refund_effects == []
    assert _ledger_rows(public_db, "C-001") == []


@pytest.mark.student
@pytest.mark.parametrize("claim_id", ["C-001", "C-005", "C-010"])
@pytest.mark.parametrize("shape", SHAPES)
def test_trace_and_result_hold_no_secret_or_pii(public_db, shape, claim_id):
    result = _run(shape)(claim_id, seed=11, store_path=str(public_db))
    trace_text = Path(result.trace_path).read_text(encoding="utf-8")
    body = json.loads(trace_text)
    assert body["run_id"] == result.run_id
    assert isinstance(body["events"], list)
    blob = trace_text + json.dumps(result.__dict__, default=str, ensure_ascii=False)
    assert "CANARY_SECRET_" not in blob
    for needle in BY_ID[claim_id]["expected"]["forbid_substrings"]:
        assert needle not in blob, f"{needle!r} leaked in {shape} {claim_id}"
