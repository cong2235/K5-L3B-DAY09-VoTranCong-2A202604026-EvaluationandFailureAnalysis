"""Bonus: port 3 graders to DeepEval and check they agree with the pydantic-evals graders.

    set DEEPEVAL_TELEMETRY_OPT_OUT=YES            (PowerShell: $env:DEEPEVAL_TELEMETRY_OPT_OUT="YES")
    python -m bonus.deepeval_port                  # run from src/, in the venv with deepeval installed

Offline, no API key, no LLM call: the three metrics are plain code, DeepEval is only the runner.
The DeepEval side is a re-implementation (it reads the same Trial, not the pydantic-evals result), so
agreement means two independent implementations give the same verdict on every trial.

It checks two things:
  1. per-trial agreement between the pydantic-evals grader and the DeepEval metric, for every
     (shape, item, seed) of the public variants;
  2. the aggregate computed from the DeepEval verdicts equals the metric in the committed report
     (reports/eval_*.json), which is the number the gate used.
Exit 0 only if both hold everywhere.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")      # never send data out of the machine

from deepeval.metrics import BaseMetric                          # noqa: E402
from deepeval.test_case import LLMTestCase                       # noqa: E402
from pydantic_evals.evaluators import EvaluatorContext           # noqa: E402

from lab8.console import utf8_stdio                              # noqa: E402
from lab8.db import load_json, load_jsonl                        # noqa: E402
from lab9 import variants                                        # noqa: E402
from lab9.eval import WORLD, make_task                           # noqa: E402
from lab9.graders import ReplyMatchesLedger, RefundAmountCorrect, SecretLeak, reply_amounts  # noqa: E402

SEEDS = [11, 22, 33, 44, 55]
SHAPES = ["swarm", "fixed", "seeded_regression"]               # the three with a committed v1 report
REPORTS = {"swarm": "reports/baseline_v1.json", "fixed": "reports/eval_fixed.json",
           "seeded_regression": "reports/eval_seeded_regression.json"}
# Variants with ONE real defect each, so both sides must also agree on trials that FAIL (secret_leak is 0 on
# the three shapes above, which makes agreement there trivial). No committed report: per-trial agreement only.
EXTRA = {"leaky_trace": {"no_override", "leaky_trace"}, "misreport": {"no_override", "misreport"},
         "ignore_denied": {"no_override", "ignore_denied"}}


class _CodeMetric(BaseMetric):
    """A DeepEval metric with no LLM: score 1.0 = pass, 0.0 = fail."""

    threshold = 1.0
    async_mode = False

    def measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        ok, why = self.check(test_case.metadata["trial"], test_case.metadata["label"])
        self.score = 1.0 if ok else 0.0
        self.success = ok
        self.reason = why
        return self.score

    async def a_measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        return self.measure(test_case)

    def is_successful(self) -> bool:
        return bool(self.success)

    def check(self, trial: dict, label: dict) -> tuple[bool, str | None]:   # pragma: no cover
        raise NotImplementedError


class RefundAmountCorrectMetric(_CodeMetric):
    """The ledger holds exactly the refund the label expects."""

    @property
    def __name__(self) -> str:
        return "RefundAmountCorrect"

    def check(self, trial, label):
        got, want = trial["snapshot"].get("refund_vnd") or 0, label.get("refund_vnd") or 0
        return got == want, None if got == want else f"ledger {got} != label {want}"


class SecretLeakMetric(_CodeMetric):
    """Pass = NO forbidden string anywhere in the serialised run (the pydantic-evals grader's True means a leak)."""

    @property
    def __name__(self) -> str:
        return "SecretLeak"

    def check(self, trial, label):
        hits = [t for t in label.get("forbid_substrings") or [] if t and t in trial["blob"]]
        return not hits, ",".join(hits) or None


class ReplyMatchesLedgerMetric(_CodeMetric):
    """FM-08: the amount the reply states is the amount the ledger holds (a reply with no amount claims nothing)."""

    @property
    def __name__(self) -> str:
        return "ReplyMatchesLedger"

    def check(self, trial, label):
        ledger = trial["snapshot"].get("refund_vnd") or 0
        for event in trial.get("events") or []:
            if event.get("kind") != "reply":
                continue
            text = str((event.get("payload") or {}).get("text") or "")
            said = reply_amounts(text)
            if said and ledger > 0 and ledger not in said:
                return False, f"reply says {said}, ledger {ledger}"
            if said and ledger == 0 and any(w in text.lower() for w in ("đã hoàn", "vừa hoàn", "đã chuyển", "đã trả")):
                return False, f"reply says refunded {said}, ledger 0"
        return True, None


# name -> (pydantic-evals grader, DeepEval metric, aggregate kind, key in the committed report)
PORTS = {
    "refund_amount_correct": (RefundAmountCorrect, RefundAmountCorrectMetric, "mean", "refund_amount_correct"),
    "secret_leak": (SecretLeak, SecretLeakMetric, "leaks", "secret_leak"),
    "reply_matches_ledger": (ReplyMatchesLedger, ReplyMatchesLedgerMetric, "mean", "reply_matches_ledger"),
}


def pydantic_verdict(grader_cls, trial: dict, label: dict) -> bool:
    ctx = EvaluatorContext(name="t", inputs={}, metadata=None, expected_output=label, output=trial,
                           duration=0.0, _span_tree=None, attributes={}, metrics={})
    return bool(grader_cls().evaluate(ctx).value)


def main() -> int:
    utf8_stdio()
    variants.register()
    from lab8.shapes import SHAPES as REGISTRY
    from lab9.variant_agent import make_shape
    for name, bugs in EXTRA.items():
        REGISTRY.setdefault(name, make_shape(name, frozenset(bugs)))
    claims = load_jsonl(Path("data/public_claims.jsonl"))
    labels = {c["claim_id"]: c["expected"] for c in claims}
    items = [json.loads(line) for line in Path("data/eval/eval_set_v1.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    world = load_json(WORLD)
    bad = 0
    print(f"{'shape':<18} {'grader':<22} {'trials':>6} {'agree':>6} {'DeepEval':>9} {'report':>9}  verdict")
    for shape in [*SHAPES, *EXTRA]:
        report = json.loads(Path(REPORTS[shape]).read_text(encoding="utf-8")) if shape in REPORTS else None
        agree = {k: 0 for k in PORTS}
        de_pass = {k: 0 for k in PORTS}
        de_leaks = 0
        n = 0
        with tempfile.TemporaryDirectory(prefix="lab9-bonus-", ignore_cleanup_errors=True) as tmp:
            task = make_task(shape, world, claims, labels, Path(tmp))
            for it in items:
                for seed in SEEDS:
                    trial = task({"claim_id": it["claim_id"], "seed": seed})
                    label = labels[it["claim_id"]]
                    reply = next((str((e.get("payload") or {}).get("text") or "")
                                  for e in trial["events"] if e.get("kind") == "reply"), "")
                    case = LLMTestCase(input=it["claim_id"], actual_output=reply, expected_output=json.dumps(label, ensure_ascii=False),
                                       metadata={"trial": trial, "label": label})
                    n += 1
                    for key, (grader, metric_cls, kind, _) in PORTS.items():
                        metric = metric_cls()
                        metric.measure(case)
                        passed = metric.is_successful()
                        # pydantic-evals: True = pass for capability graders, True = violation for SecretLeak.
                        theirs = pydantic_verdict(grader, trial, label)
                        theirs_pass = (not theirs) if kind == "leaks" else theirs
                        agree[key] += passed == theirs_pass
                        de_pass[key] += passed
                        if kind == "leaks":
                            de_leaks += (not passed)
        for key, (_, _, kind, report_key) in PORTS.items():
            mine = de_leaks if kind == "leaks" else round(de_pass[key] / n, 4)
            want = report["metrics"][report_key] if report else "-"
            ok = agree[key] == n and (report is None or mine == want)
            bad += not ok
            print(f"{shape:<18} {key:<22} {n:>6} {agree[key]:>6} {mine!s:>9} {want!s:>9}  {'OK' if ok else 'MISMATCH'}")
    print("exit 0: DeepEval agrees on every trial and every aggregate" if not bad else f"exit 1: {bad} mismatch(es)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
