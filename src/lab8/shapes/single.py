"""Shape B — one bounded ReAct agent with host-only refund issuance."""

from __future__ import annotations

import sqlite3
from typing import Any, Callable

from lab8 import durability
from lab8.db import connect
from lab8.handoff import READONLY_TOOLS
from lab8.mock_llm import complete
from lab8.runtime import run_react
from lab8.schemas import Budget, RunResult, make_run_id
from lab8.shapes import common
from lab8.tools import get_claim_view, tool_cost
from lab8.trace import Trace

MAX_STEPS = 8
ALLOWED_READ_TOOLS = frozenset(READONLY_TOOLS)


def _build_decide_fn(
    budget: Budget,
    trace: Trace,
    *,
    order_id: str,
    principal_id: str,
    seed: int,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Choose only read tools, retaining the allowlisted order view privately."""
    state: dict[str, Any] = {}

    def select_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
        if name not in ALLOWED_READ_TOOLS:
            raise PermissionError(f"Tool {name!r} is not available to the ReAct worker.")
        trace.add("tool_selected", common.safe_dump({"tool": name}))
        return {"tool": name, "args": args}

    def decide(observation: dict[str, Any]) -> dict[str, Any]:
        last_tool = observation.get("last_tool")
        result = observation.get("last_result")
        if last_tool is None:
            result_state = "initial"
        elif last_tool in {"lookup_order", "lookup_refund_history"}:
            result_state = (
                "visible"
                if isinstance(result, dict) and result.get("visible")
                else "not_visible"
            )
        elif last_tool == "lookup_policy":
            result_state = "policy_loaded"
        elif last_tool == "compute_compensation":
            result_state = "quote_ready"
        else:
            result_state = "unexpected"

        model_tool = last_tool if last_tool in ALLOWED_READ_TOOLS else "none"
        prompt = (
            f"step={budget.model_calls + 1};tool={model_tool};"
            f"result_state={result_state}"
        )
        complete(budget, seed=seed, purpose="react_decide", prompt=prompt)

        if last_tool == "lookup_order":
            if not isinstance(result, dict) or not result.get("visible"):
                reason = (
                    result.get("reason", "order_not_visible")
                    if isinstance(result, dict)
                    else "order_not_visible"
                )
                return {"final": {"status": "escalated", "reason": reason}}
            order = result.get("order")
            if not isinstance(order, dict):
                return {"final": {"status": "failed", "reason": "invalid_order_view"}}
            state["order"] = order
            return select_tool(
                "lookup_refund_history",
                {"order_id": order_id, "principal_id": principal_id},
            )

        if last_tool == "lookup_refund_history":
            if not isinstance(result, dict) or not result.get("visible"):
                reason = (
                    result.get("reason", "refund_history_not_visible")
                    if isinstance(result, dict)
                    else "refund_history_not_visible"
                )
                return {"final": {"status": "escalated", "reason": reason}}
            return select_tool("lookup_policy", {})

        if last_tool == "lookup_policy":
            return select_tool("compute_compensation", {"order": state["order"]})

        if last_tool == "compute_compensation":
            return {"final": {"status": "quoted", "quote": result}}

        if last_tool is not None:
            return {"final": {"status": "failed", "reason": "unexpected_react_state"}}

        return select_tool(
            "lookup_order",
            {"order_id": order_id, "principal_id": principal_id},
        )

    return decide


def _finish(
    conn: sqlite3.Connection,
    *,
    claim_id: str,
    seed: int,
    budget: Budget,
    trace: Trace,
    status: str,
    proposal_amount: int = 0,
    error_reason: str | None = None,
) -> RunResult:
    return common.finish(
        conn,
        shape="single",
        claim_id=claim_id,
        seed=seed,
        status=status,
        proposal_amount=proposal_amount,
        budget=budget,
        trace=trace,
        error_reason=error_reason,
    )


def run_claim(
    claim_id: str,
    *,
    seed: int,
    store_path: str,
    crash_at: str | None = None,
) -> RunResult:
    run_id = make_run_id("single", claim_id, seed)
    trace = Trace(run_id)
    budget = Budget()
    conn = connect(store_path)

    try:
        # Keep only the identifiers needed by read tools; never pass ticket text onward.
        claim = get_claim_view(conn, claim_id)
        budget.add_tool(tool_cost())
        claim_context = {
            key: claim[key]
            for key in ("claim_id", "order_id", "principal_id")
            if key in claim
        }
        trace.add(
            "claim_view",
            common.safe_dump(
                {
                    "found": bool(claim.get("found")),
                    "has_order": bool(claim_context.get("order_id")),
                }
            ),
        )

        if not claim.get("found"):
            return _finish(
                conn,
                claim_id=claim_id,
                seed=seed,
                budget=budget,
                trace=trace,
                status="failed",
                error_reason="unknown_claim",
            )

        order_id = claim_context.get("order_id")
        if not order_id:
            return _finish(
                conn,
                claim_id=claim_id,
                seed=seed,
                budget=budget,
                trace=trace,
                status="needs_info",
                error_reason="missing_order_id",
            )

        outcome = run_react(
            conn,
            budget,
            observation={"claim": {"claim_id": claim_id}},
            decide=_build_decide_fn(
                budget,
                trace,
                order_id=order_id,
                principal_id=claim_context["principal_id"],
                seed=seed,
            ),
            max_steps=MAX_STEPS,
            worker=True,
        )
        if outcome.get("stopped") == "step_cap":
            trace.add("stopped", {"reason": "step_cap"})
            return _finish(
                conn,
                claim_id=claim_id,
                seed=seed,
                budget=budget,
                trace=trace,
                status="failed",
                error_reason="step_cap",
            )

        final = outcome.get("final") or {}
        status = final.get("status")
        if status == "escalated":
            return _finish(
                conn,
                claim_id=claim_id,
                seed=seed,
                budget=budget,
                trace=trace,
                status="escalated",
                error_reason=final.get("reason"),
            )
        if status != "quoted":
            reason = final.get("reason") or "invalid_react_result"
            return _finish(
                conn,
                claim_id=claim_id,
                seed=seed,
                budget=budget,
                trace=trace,
                status="failed",
                error_reason=reason,
            )

        quote = final.get("quote")
        if not isinstance(quote, dict):
            return _finish(
                conn,
                claim_id=claim_id,
                seed=seed,
                budget=budget,
                trace=trace,
                status="failed",
                error_reason="invalid_quote",
            )
        amount = quote.get("amount_vnd")
        reason = quote.get("reason")
        if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
            return _finish(
                conn,
                claim_id=claim_id,
                seed=seed,
                budget=budget,
                trace=trace,
                status="failed",
                error_reason="invalid_quote",
            )

        trace.add(
            "quote",
            common.safe_dump({"amount_vnd": amount, "reason": reason}),
        )
        if amount == 0:
            return _finish(
                conn,
                claim_id=claim_id,
                seed=seed,
                budget=budget,
                trace=trace,
                status="denied",
                error_reason=reason or "zero_compensation",
            )

        # The host alone writes, and durability applies approval and per-order caps.
        trace.add("host_issue_refund", {"amount_vnd": amount})
        trace.write()
        refund = durability.issue_refund(
            conn,
            claim_id=claim_id,
            proposed_vnd=amount,
            crash_at=crash_at,
        )
        trace.add(
            "refund_result",
            common.safe_dump(
                {
                    "ok": bool(refund.get("ok")),
                    "reason": refund.get("reason"),
                    "conflict": bool(refund.get("conflict")),
                }
            ),
        )
        if not refund.get("ok"):
            return _finish(
                conn,
                claim_id=claim_id,
                seed=seed,
                budget=budget,
                trace=trace,
                status="failed" if refund.get("conflict") else "denied",
                proposal_amount=amount,
                error_reason=refund.get("reason"),
            )

        return _finish(
            conn,
            claim_id=claim_id,
            seed=seed,
            budget=budget,
            trace=trace,
            status="resolved",
            proposal_amount=amount,
        )
    finally:
        conn.close()
