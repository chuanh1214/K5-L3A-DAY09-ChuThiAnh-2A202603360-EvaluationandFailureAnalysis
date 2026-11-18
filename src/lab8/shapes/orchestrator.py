"""Shape C — orchestrator plus read-only investigators."""

from __future__ import annotations

import sqlite3

from lab8.db import connect
from lab8.durability import InjectedCrash, issue_refund
from lab8.handoff import make_handoff
from lab8.runtime import run_readonly_investigators
from lab8.schemas import Budget, RunResult, make_run_id
from lab8.shapes.common import finish, safe_dump
from lab8.tools import tool_cost


def run_claim(
    claim_id: str,
    *,
    seed: int,
    store_path: str,
    crash_at: str | None = None,
) -> RunResult:
    conn = connect(store_path)
    try:
        return _run(
            conn,
            claim_id,
            seed=seed,
            crash_at=crash_at,
        )
    finally:
        conn.close()


def _run(
    conn: sqlite3.Connection,
    claim_id: str,
    *,
    seed: int,
    crash_at: str | None,
) -> RunResult:
    shape = "orchestrator"
    budget = Budget()
    run_id = make_run_id(shape, claim_id, seed)

    from lab8.trace import Trace

    trace = Trace(run_id)

    claim_row = conn.execute(
        """
        SELECT claim_id, principal_id, order_id
        FROM claims
        WHERE claim_id = ?
        """,
        (claim_id,),
    ).fetchone()

    budget.add_tool(tool_cost())

    if claim_row is None:
        trace.add("error", {"reason": "unknown_claim"})
        return finish(
            conn,
            shape=shape,
            claim_id=claim_id,
            seed=seed,
            status="failed",
            proposal_amount=0,
            budget=budget,
            trace=trace,
            error_reason="unknown_claim",
        )

    if not claim_row["order_id"]:
        trace.add("decision", {"status": "needs_info"})
        return finish(
            conn,
            shape=shape,
            claim_id=claim_id,
            seed=seed,
            status="needs_info",
            proposal_amount=0,
            budget=budget,
            trace=trace,
            error_reason="missing_order_id",
        )

    handoff = make_handoff(
        request_id=f"REQ-{claim_id}",
        claim_id=claim_id,
        task="check_applicable_policy",
        facts={},
        allowed_tools=[
            "lookup_order",
            "lookup_policy",
            "compute_compensation",
        ],
    )

    trace.add("handoff", safe_dump(handoff))

    investigated = run_readonly_investigators(
        conn,
        budget,
        handoff,
        principal_id=claim_row["principal_id"],
    )

    order_view = investigated["tools"].get("lookup_order", {})
    policy_view = investigated["tools"].get("lookup_policy", {})

    trace.add(
        "investigator",
        {
            "lookup_order": safe_dump(order_view),
            "policy_count": len(policy_view.get("policies") or []),
        },
    )

    if not order_view.get("visible"):
        trace.add(
            "decision",
            {
                "status": "escalated",
                "reason": order_view.get("reason"),
            },
        )
        return finish(
            conn,
            shape=shape,
            claim_id=claim_id,
            seed=seed,
            status="escalated",
            proposal_amount=0,
            budget=budget,
            trace=trace,
            error_reason=order_view.get("reason"),
        )

    quote_payload = investigated["tools"].get("compute_compensation", {})
    proposal = int(quote_payload.get("amount_vnd", 0))

    trace.add("quote", safe_dump(quote_payload))

    if proposal <= 0:
        trace.add(
            "decision",
            {
                "status": "denied",
                "reason": quote_payload.get("reason"),
            },
        )
        return finish(
            conn,
            shape=shape,
            claim_id=claim_id,
            seed=seed,
            status="denied",
            proposal_amount=0,
            budget=budget,
            trace=trace,
            error_reason=quote_payload.get("reason"),
        )

    try:
        outcome = issue_refund(
            conn,
            claim_id,
            proposal,
            crash_at=crash_at,
        )
    except InjectedCrash:
        trace.add("crash", {"at": crash_at})
        trace.write()
        raise

    if not outcome["ok"]:
        status = "failed" if outcome["conflict"] else "denied"

        trace.add(
            "decision",
            {
                "status": status,
                "reason": outcome["reason"],
            },
        )

        return finish(
            conn,
            shape=shape,
            claim_id=claim_id,
            seed=seed,
            status=status,
            proposal_amount=proposal,
            budget=budget,
            trace=trace,
            error_reason=outcome["reason"],
        )

    trace.add("decision", {"status": "resolved"})

    return finish(
        conn,
        shape=shape,
        claim_id=claim_id,
        seed=seed,
        status="resolved",
        proposal_amount=proposal,
        budget=budget,
        trace=trace,
        error_reason=None,
    )
