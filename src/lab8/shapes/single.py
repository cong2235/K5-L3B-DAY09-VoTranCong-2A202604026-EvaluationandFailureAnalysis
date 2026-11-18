"""Shape B — one ReAct agent. Student work.

Use `lab8.runtime.run_react` with max_steps=8. `decide` may pick a read tool.
It must not call `issue_refund`. After the loop, the host validates the quote
and is the only writer.

A decide() that trusts ticket text over the order row will fail hidden claims
where the customer overstates the delay or cites a superseded clause.

Per-order cap: an order may already have been refunded by an earlier claim.
The read tool `lookup_refund_history` shows how much. The host still enforces
the cap, so pass the full quote to `durability.issue_refund`, not a net amount.

Caps: stop at 8 steps. Count model calls in the Budget so cost stays comparable.

Trace contract v1 (docs/contracts.md): return a trace_path to a JSON file written in this run,
{"run_id": <same run_id>, "events": [...]}, on every return path including early
ones. `lab8.trace.Trace` does this; your own tracer is fine if it matches.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from lab8.db import connect
from lab8.durability import InjectedCrash, issue_refund
from lab8.mock_llm import complete
from lab8.runtime import ToolRejected, run_react
from lab8.schemas import Budget, RunResult, make_run_id
from lab8.shapes.common import finish, safe_dump
from lab8.tools import get_claim_view, tool_cost
from lab8.trace import Trace

SHAPE = "single"
MAX_STEPS = 8


def run_claim(
    claim_id: str,
    *,
    seed: int,
    store_path: str,
    crash_at: str | None = None,
) -> RunResult:
    conn = connect(store_path)
    try:
        return _run(conn, claim_id, seed=seed, crash_at=crash_at)
    finally:
        conn.close()


def _run(conn: sqlite3.Connection, claim_id: str, *, seed: int, crash_at: str | None) -> RunResult:
    budget = Budget()
    trace = Trace(make_run_id(SHAPE, claim_id, seed))

    def done(status: str, amount: int, reason: str | None = None) -> RunResult:
        return finish(
            conn,
            shape=SHAPE,
            claim_id=claim_id,
            seed=seed,
            status=status,
            proposal_amount=amount,
            budget=budget,
            trace=trace,
            error_reason=reason,
        )

    # Read the claim through the allowlisted view. The ticket stays out of the
    # ReAct observation and out of the trace: it is user data, never an instruction.
    budget.add_tool(tool_cost())
    view = get_claim_view(conn, claim_id)
    if not view["found"]:
        trace.add("error", {"reason": "unknown_claim"})
        return done("failed", 0, "unknown_claim")

    claim = {
        "claim_id": view["claim_id"],
        "principal_id": view["principal_id"],
        "order_id": view["order_id"],
    }
    if not claim["order_id"]:
        complete(budget, seed=seed, purpose="draft", prompt="needs_info")
        trace.add("decision", {"status": "needs_info"})
        return done("needs_info", 0, "missing_order_id")

    # The model only picks read tools. State lives outside the loop because
    # run_react hands decide() just the last tool result.
    state: dict[str, Any] = {}

    def decide(seen: dict[str, Any]) -> dict[str, Any]:
        last = seen.get("last_tool")
        complete(budget, seed=seed, purpose="react", prompt=str(last or "start"))
        result = seen.get("last_result") or {}
        if last is None:
            return {
                "tool": "lookup_order",
                "args": {"order_id": claim["order_id"], "principal_id": claim["principal_id"]},
            }
        if last == "lookup_order":
            trace.add("observation", {"tool": last, "result": safe_dump(result)})
            if not result.get("visible"):
                return {"final": {"status": "escalated", "error_reason": result.get("reason")}}
            # Delay comes from the order row only, never from the ticket text.
            return {"tool": "compute_compensation", "args": {"order": result["order"]}}
        if last == "compute_compensation":
            trace.add("observation", {"tool": last, "result": safe_dump(result)})
            state["quote"] = result
            return {"final": {"quote": int(result["amount_vnd"]), "error_reason": result.get("reason")}}
        return {"final": {"status": "failed", "error_reason": "unexpected_tool"}}

    try:
        loop = run_react(
            conn,
            budget,
            observation={"claim": claim},
            decide=decide,
            max_steps=MAX_STEPS,
        )
    except ToolRejected as exc:
        trace.add("error", {"reason": "tool_rejected", "detail": str(exc)})
        return done("failed", 0, "tool_rejected")

    final = loop["final"]
    trace.add("loop", {"stopped": loop["stopped"], "steps": budget.steps})

    # Terminal states decided inside the loop (escalated, step_cap, bad tool).
    if "status" in final:
        if final["status"] == "escalated":
            complete(budget, seed=seed, purpose="draft", prompt="escalated")
        return done(final["status"], 0, final.get("error_reason"))

    quote = int(final["quote"])
    complete(budget, seed=seed, purpose="draft", prompt=f"proposal={quote}")

    if quote <= 0:
        # Nothing to pay, so issue_refund is never called.
        trace.add("decision", {"status": "denied", "quote": 0})
        return done("denied", 0, final.get("error_reason"))

    # Host is the only writer. Pass the FULL quote: the host subtracts what
    # earlier claims already got for this order. Do not catch InjectedCrash.
    try:
        outcome = issue_refund(conn, claim_id, quote, crash_at=crash_at)
    except InjectedCrash:
        trace.add("crash", {"at": crash_at})
        trace.write()
        raise

    trace.add("host", {"ok": outcome["ok"], "reason": outcome["reason"], "conflict": outcome["conflict"]})
    if not outcome["ok"]:
        status = "failed" if outcome["conflict"] else "denied"
        return done(status, quote, outcome["reason"])
    return done("resolved", quote, None)
