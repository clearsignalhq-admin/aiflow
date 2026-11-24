"""Run test-suite cases and summarise a run (Tasks 50, 55).

Each case is one simulation of the workflow snapshot. Cases run auto-approve HITL and expression routing
(a suite must never pause), seeded so results are reproducible: a case uses its own ``seed`` or
``run_seed + index``.

``llm_mode="mock"`` (default) is free and exactly reproducible. ``llm_mode="real"`` calls the AI model for
every LLM step the case reaches: results can vary between runs, each model call is billed against the
user's LLM-request allowance, and a pinned ``mock_output`` on an LLM step is ignored.
"""
import asyncio
import json
import logging
import time
from typing import Any, Optional

from app.core.config import settings as app_settings
from app.models.workflow import NodeType, Workflow
from app.schemas.simulation import (
    ConditionMode,
    ExecutionTrace,
    HITLMode,
    LLMMode,
    NodeExecutionStatus,
    SimulationSettings,
)
from app.schemas.suites import CaseResult, Coverage, RunReport
from app.services.assertions import AssertionContext, evaluate_assertions
from app.services.linter import lint_workflow
from app.services.simulator import SimulationError, simulate

logger = logging.getLogger(__name__)

_MAX_OUTPUT_BYTES = 5_000
_MAX_WARNINGS = 10


def case_settings(case: dict[str, Any], index: int, run_seed: int, llm_mode: str = "mock") -> SimulationSettings:
    seed = case.get("seed")
    return SimulationSettings(
        llm_mode=LLMMode.REAL if llm_mode == "real" else LLMMode.MOCK,
        hitl_mode=HITLMode.AUTO_APPROVE,
        condition_mode=ConditionMode.EXPRESSION,
        evaluate=False,
        seed=seed if isinstance(seed, int) else run_seed + index,
    )


def final_output(trace: ExecutionTrace) -> Any:
    """The ``result`` of the last END node executed, or None."""
    ends = [s for s in trace.steps if s.node_type == NodeType.END.value and s.status == NodeExecutionStatus.SUCCESS]
    if not ends:
        return None
    output = ends[-1].output
    return output.get("result") if isinstance(output, dict) and "result" in output else output


def _compact_output(output: Any) -> Any:
    try:
        text = json.dumps(output, default=str)
    except (TypeError, ValueError):
        return {"_unserialisable": True}
    if len(text) <= _MAX_OUTPUT_BYTES:
        return output
    return {"_truncated": True, "preview": text[:500]}


def _llm_calls(trace: Optional[ExecutionTrace]) -> int:
    """Model calls a real-mode trace made: every LLM step that started, including one that failed."""
    return sum(1 for s in trace.steps if s.node_type == NodeType.LLM.value) if trace else 0


def _error_result(case: dict[str, Any], started: float, message: str, node_id: Optional[str] = None,
                  trace: Optional[ExecutionTrace] = None, llm_calls: int = 0) -> CaseResult:
    return CaseResult(
        case_id=case["id"], case_name=case["name"], status="error", llm_calls=llm_calls,
        duration_ms=int((time.perf_counter() - started) * 1000), error=message, error_node_id=node_id,
        path=[s.node_id for s in trace.steps] if trace else [],
        edges_taken=_edges(trace) if trace else [],
    )


def _edges(trace: ExecutionTrace) -> list[str]:
    return [f"{s.node_id}→{t}" for s in trace.steps for t in s.next_ids]


async def run_case(workflow: Workflow, case: dict[str, Any], index: int, run_seed: int,
                   timeout: Optional[float] = None, llm_mode: str = "mock",
                   timeout_llm_calls: int = 0) -> CaseResult:
    """Simulate one case and evaluate its assertions. Never raises: problems become ``error`` results.

    ``timeout_llm_calls`` is what to report as used when the case times out (its trace is lost, so the
    caller passes the most the workflow could have called, which is the safe amount to charge).
    """
    real = llm_mode == "real"
    limit = timeout if timeout is not None else app_settings.simulation_timeout_seconds
    started = time.perf_counter()
    case_input = case.get("input") if isinstance(case.get("input"), dict) else {}
    try:
        trace = await asyncio.wait_for(
            simulate(workflow, case_input, case_settings(case, index, run_seed, llm_mode)), timeout=limit,
        )
    except asyncio.TimeoutError:
        return _error_result(case, started, f"Timed out after {limit:g}s", llm_calls=timeout_llm_calls if real else 0)
    except SimulationError as exc:
        return _error_result(case, started, str(exc))
    except Exception as exc:  # a broken case must not break the run
        logger.warning("Suite case %s failed unexpectedly: %s", case.get("id"), exc)
        return _error_result(case, started, f"Unexpected error: {exc}", llm_calls=timeout_llm_calls if real else 0)

    calls = _llm_calls(trace) if real else 0
    if trace.status != "complete":
        failing = next((s for s in trace.steps if s.status == NodeExecutionStatus.ERROR), None)
        return _error_result(
            case, started, failing.error if failing and failing.error else f"Simulation ended as '{trace.status}'",
            node_id=failing.node_id if failing else None, trace=trace, llm_calls=calls,
        )

    output = final_output(trace)
    path = [s.node_id for s in trace.steps]
    outcomes = evaluate_assertions(
        case.get("assertions") or [],
        AssertionContext(output=output, input=case_input, visited=path, step_count=len(trace.steps), status=trace.status),
    )
    warnings = [f"{s.node_name}: {w}" for s in trace.steps for w in s.warnings][:_MAX_WARNINGS]
    return CaseResult(
        case_id=case["id"], case_name=case["name"], llm_calls=calls,
        status="passed" if all(o.passed for o in outcomes) else "failed",
        duration_ms=int((time.perf_counter() - started) * 1000),
        assertion_results=[o.model_dump() for o in outcomes],
        output=_compact_output(output), path=path, edges_taken=_edges(trace), warnings=warnings,
    )


def llm_use_per_case(workflow: Workflow) -> tuple[int, float]:
    """The most model calls, and the rough cost, one case can use: the worst route through the workflow.

    Falls back to every LLM step in the workflow when routes cannot be enumerated (for example a cycle).
    """
    llm_ids = {n.id for n in workflow.nodes if n.type == NodeType.LLM}
    estimates = lint_workflow(workflow).estimates
    if not estimates:
        calls = len(llm_ids)
        return calls, round(calls * _COST_PER_LLM_CALL, 6)
    best = max(estimates, key=lambda e: (sum(1 for i in e.node_ids if i in llm_ids), e.cost_usd))
    return sum(1 for i in best.node_ids if i in llm_ids), best.cost_usd


_COST_PER_LLM_CALL = 0.002      # keep in step with the per-LLM-call assumption in services/linter.py


# ── Aggregation ──────────────────────────────────────────────────────────────

def build_report(workflow: dict[str, Any], case_count: int, results: list[dict[str, Any]]) -> RunReport:
    """Pass rate and coverage for a (possibly still running) job, from stored workflow + case results."""
    nodes = [n["id"] for n in workflow.get("nodes", [])]
    edges = workflow.get("edges", [])

    node_visits = {nid: 0 for nid in nodes}
    edges_taken: dict[str, int] = {}
    node_failures: dict[str, int] = {}
    counts = {"passed": 0, "failed": 0, "error": 0}

    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
        for nid in set(r.get("path") or []):
            node_visits[nid] = node_visits.get(nid, 0) + 1
        for key in set(r.get("edges_taken") or []):
            edges_taken[key] = edges_taken.get(key, 0) + 1
        if r["status"] != "passed":
            touched = set(r.get("path") or [])
            if r.get("error_node_id"):
                touched.add(r["error_node_id"])
            for nid in touched:
                node_failures[nid] = node_failures.get(nid, 0) + 1

    never_taken = [
        {"source": e["source"], "target": e["target"], "label": e.get("condition")}
        for e in edges if f"{e['source']}→{e['target']}" not in edges_taken
    ]
    completed = len(results)
    return RunReport(
        total=case_count, completed=completed,
        passed=counts["passed"], failed=counts["failed"], errors=counts["error"],
        pass_rate=round(counts["passed"] / completed, 4) if completed else None,
        llm_calls=sum(int(r.get("llm_calls") or 0) for r in results),
        coverage=Coverage(
            node_visits=node_visits,
            never_visited=[nid for nid in nodes if node_visits.get(nid, 0) == 0],
            edges_taken=edges_taken,
            edges_never_taken=never_taken,
            node_failures=node_failures,
        ),
    )
