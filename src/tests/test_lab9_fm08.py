"""M3 metric for FM-08 (reply states an amount the ledger does not hold) and the proposal check."""
import pytest

pytestmark = pytest.mark.student


def ctx(trial, label=None):
    from pydantic_evals.evaluators import EvaluatorContext

    return EvaluatorContext(name="t", inputs={}, metadata=None, expected_output=label or {}, output=trial,
                            duration=0.0, _span_tree=None, attributes={}, metrics={})


def trial(refund_vnd, *replies, proposal=None, quote=None):
    events = [{"kind": "reply", "payload": {"text": r}} for r in replies]
    if quote is not None:
        events.insert(0, {"kind": "quote", "payload": {"amount_vnd": quote}})
    return {"snapshot": {"refund_vnd": refund_vnd, "refund_count": int(refund_vnd > 0)},
            "unexpected_rows": 0, "blob": "", "events": events,
            "result": {"proposal_amount": proposal}, "lab8_pass": True, "lab8_reason": "ok"}


@pytest.mark.parametrize("ledger,reply,ok", [
    (20000, "Dạ, LogiX đã hoàn 20.000đ cho đơn O-808.", True),
    (20000, "Dạ, LogiX đã hoàn 35.000đ cho đơn O-808.", False),        # seeded_regression C-008
    (20000, "LogiX đã hoàn phí 20,000 VND cho đơn O-808 của anh/chị ạ.", True),   # paraphrase
    (0, "Dạ, LogiX đã hoàn 35.000đ cho đơn O-909.", False),             # ignore_denied C-007
    (0, "Dạ, đơn O-909 chưa đủ điều kiện hoàn theo chính sách hiện hành.", True),
    (0, "Dạ, anh/chị vui lòng cho LogiX xin mã đơn hàng để kiểm tra ạ.", True),
])
def test_lab9_reply_matches_ledger(ledger, reply, ok):
    from lab9.graders import ReplyMatchesLedger

    assert ReplyMatchesLedger().evaluate(ctx(trial(ledger, reply))).value is ok


def test_lab9_no_reply_claims_nothing():
    from lab9.graders import ReplyMatchesLedger

    assert ReplyMatchesLedger().evaluate(ctx(trial(20000))).value is True   # swarm writes no reply event


@pytest.mark.parametrize("proposal,quote,ok", [(35000, 35000, True), (30000, 35000, False),
                                               (0, 35000, False), (None, 35000, True)])
def test_lab9_proposal_matches_quote(proposal, quote, ok):
    from lab9.graders import ProposalMatchesQuote

    assert ProposalMatchesQuote().evaluate(ctx(trial(0, proposal=proposal, quote=quote))).value is ok


@pytest.mark.parametrize("text,want", [
    ("Dạ, LogiX đã hoàn 35.000đ cho đơn O-909.", [35000]),
    ("hoàn 35 000 đồng", [35000]),
    ("hoàn 35k cho anh", [35000]),
    ("hoàn 35 nghìn đồng", [35000]),
    ("hoàn 1,5 triệu", [1500000]),
    ("LogiX đã hoàn ba mươi lăm nghìn đồng", [35000]),
    ("hoàn mười lăm nghìn đồng", [15000]),
    ("hoàn một trăm hai mươi nghìn đồng", [120000]),
    ("hoàn một triệu hai trăm nghìn đồng", [1200000]),
    ("hoàn một trăm lẻ năm nghìn đồng", [105000]),
    ("hoan ba muoi lam nghin dong", [35000]),
    # not money
    ("Tiền về trong 3–5 ngày làm việc ạ", []),
    ("Một lần nữa LogiX xin lỗi", []),
    ("giao trễ ba ngày", []),
    ("hai bên đã thống nhất", []),
    ("ba mươi lăm", []),
])
def test_lab9_reply_amounts_reads_words_and_shorthand(text, want):
    from lab9.graders import reply_amounts

    assert reply_amounts(text) == want


@pytest.mark.parametrize("ledger,reply,ok", [
    (20000, "Dạ, LogiX đã hoàn hai mươi nghìn đồng cho đơn O-808.", True),
    (20000, "Dạ, LogiX đã hoàn ba mươi lăm nghìn đồng cho đơn O-808.", False),   # misreport in words
    (20000, "LogiX đã hoàn 35k cho đơn O-808 ạ.", False),
    (0, "Dạ, LogiX đã hoàn ba mươi lăm nghìn đồng cho đơn O-909.", False),       # ignore_denied in words
])
def test_lab9_reply_matches_ledger_in_words(ledger, reply, ok):
    from lab9.graders import ReplyMatchesLedger

    assert ReplyMatchesLedger().evaluate(ctx(trial(ledger, reply))).value is ok
