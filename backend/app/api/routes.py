import asyncio
import logging
import time

from fastapi import APIRouter, HTTPException, status as http_status
from app.schemas.requests import (
    GenerateWorkflowRequest,
    GenerateWorkflowResponse,
    ValidateWorkflowRequest,
    ValidateWorkflowResponse,
    WorkflowChatRequest,
    WorkflowChatResponse,
)
from app.schemas.simulation import (
    LLMMode,
    ResumeSimulationRequest,
    SimulateWorkflowRequest,
    SimulateWorkflowResponse,
)
from app.services.validator import validate_workflow
from app.services.linter import lint_workflow
from app.schemas.lint import LintWorkflowRequest, LintWorkflowResponse
from app.schemas.explain import ExplainWorkflowRequest, ExplainWorkflowResponse
from app.services.explainer import explain_workflow
from app.services.workflow_generator import generate_workflow, chat_workflow_service, WorkflowGenerationError
from app.services.simulator import (
    simulate, resume_simulation, get_paused_settings, export_paused_state, SimulationError, InvalidResumeError,
)
from app.services.evaluator import mock_evaluate, llm_evaluate, EvaluationError
from app.services import run_persistence
from app.providers.factory import get_provider
from app.api.deps import ApprovedUser
from app.core.config import settings
from app.core.supabase_client import get_usage_today, increment_usage, insert_analytics_event
from app.models.user import UserProfile

router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)


class _Budget:
    """Wall-clock budget for one request (see Settings.request_budget_seconds)."""

    def __init__(self, total: float):
        self._deadline = time.monotonic() + total

    def remaining(self) -> float:
        return self._deadline - time.monotonic()


async def _llm_call(coro):
    """Run a provider call under the LLM timeout; a timeout becomes a clear 504."""
    limit = settings.llm_timeout_seconds
    try:
        return await asyncio.wait_for(coro, timeout=limit)
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail=f"The AI request timed out after {limit:g}s. Please try again, or use a shorter description.",
        )


async def _evaluate(
    user: UserProfile,
    workflow,
    trace,
    sim_settings,
    budget: _Budget,
    check_limit: bool,
):
    """Evaluate a completed trace, within what is left of the request budget.

    Mock evaluation is instant. The LLM evaluation falls back to the mock one, with the reason
    recorded on the result, if it fails, times out, or there is no time left for it.
    """
    if not sim_settings.evaluate or trace.status != "complete":
        return None
    if sim_settings.llm_mode == LLMMode.MOCK:
        return mock_evaluate(workflow, trace)

    if check_limit:
        await _check_llm_limit(user)
    available = budget.remaining() - settings.persist_reserve_seconds
    if available < settings.min_llm_evaluation_seconds:
        evaluation = mock_evaluate(workflow, trace)
        evaluation.fallback_reason = "LLM evaluation skipped: not enough time left in this request"
        return evaluation
    try:
        provider = get_provider()
        evaluation = await asyncio.wait_for(llm_evaluate(workflow, trace, provider), timeout=available)
        await increment_usage(user.id, "llm_requests")
        return evaluation
    except asyncio.TimeoutError:
        reason = f"LLM evaluation timed out after {available:.0f}s"
    except (RuntimeError, EvaluationError) as exc:
        reason = f"LLM evaluation unavailable ({exc})"
    logger.warning("LLM evaluation fell back to mock: %s", reason)
    evaluation = mock_evaluate(workflow, trace)
    evaluation.fallback_reason = reason
    return evaluation


async def _check_llm_limit(user: UserProfile) -> None:
    """Raise 429 if the user has hit their daily LLM request limit."""
    max_llm = (
        settings.demo_max_llm_requests_per_day
        if user.role == "demo"
        else settings.approved_max_llm_requests_per_day
    )
    if max_llm <= 0:
        return  # 0 = unlimited
    usage = await get_usage_today(user.id)
    if usage.get("llm_requests", 0) >= max_llm:
        raise HTTPException(
            status_code=http_status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Daily AI request limit ({max_llm}) reached. Try again tomorrow.",
        )


async def _check_execution_limit(user: UserProfile) -> None:
    """Raise 429 if the user has hit their daily execution limit."""
    max_exec = (
        settings.demo_max_executions_per_day
        if user.role == "demo"
        else settings.approved_max_executions_per_day
    )
    if max_exec <= 0:
        return
    usage = await get_usage_today(user.id)
    if usage.get("executions", 0) >= max_exec:
        raise HTTPException(
            status_code=http_status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Daily execution limit ({max_exec}) reached. Try again tomorrow.",
        )


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.post("/workflows/validate", response_model=ValidateWorkflowResponse)
async def validate(request: ValidateWorkflowRequest, user: ApprovedUser):
    result = validate_workflow(request.workflow)
    return ValidateWorkflowResponse(
        valid=result.valid,
        errors=result.errors,
        warnings=result.warnings,
    )


@router.post("/workflows/lint", response_model=LintWorkflowResponse)
async def lint(request: LintWorkflowRequest, user: ApprovedUser):
    return LintWorkflowResponse(**lint_workflow(request.workflow).model_dump())


@router.post("/workflows/explain", response_model=ExplainWorkflowResponse)
async def explain(request: ExplainWorkflowRequest, user: ApprovedUser):
    """Deterministic plain-language description (no LLM, so it costs no allowance)."""
    return ExplainWorkflowResponse(markdown=explain_workflow(request.workflow))


@router.post("/workflows/generate", response_model=GenerateWorkflowResponse)
async def generate(request: GenerateWorkflowRequest, user: ApprovedUser):
    await _check_llm_limit(user)

    try:
        provider = get_provider()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    try:
        workflow = await _llm_call(generate_workflow(request.description, provider))
    except WorkflowGenerationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    await increment_usage(user.id, "llm_requests")
    await insert_analytics_event("workflow_generate", user_id=user.id)
    return GenerateWorkflowResponse(workflow=workflow)


@router.post("/workflows/chat", response_model=WorkflowChatResponse)
async def chat_workflow(request: WorkflowChatRequest, user: ApprovedUser):
    await _check_llm_limit(user)

    try:
        provider = get_provider()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    try:
        result = await _llm_call(chat_workflow_service(request.messages, request.current_workflow, provider))
    except WorkflowGenerationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    await increment_usage(user.id, "llm_requests")
    return result


@router.post("/workflows/simulate", response_model=SimulateWorkflowResponse)
async def simulate_workflow(request: SimulateWorkflowRequest, user: ApprovedUser):
    budget = _Budget(settings.request_budget_seconds)
    await _check_execution_limit(user)

    limit = min(settings.simulation_timeout_seconds, budget.remaining())
    try:
        trace = await asyncio.wait_for(
            simulate(request.workflow, request.input, request.settings),
            timeout=limit,
        )
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail=f"Simulation timed out after {limit:g}s. Try mock mode or a smaller workflow.",
        )
    except SimulationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    await increment_usage(user.id, "executions")
    await insert_analytics_event("workflow_simulate", user_id=user.id)

    evaluation = await _evaluate(user, request.workflow, trace, request.settings, budget, check_limit=True)

    run_id = await run_persistence.persist_run(
        user.id, request.workflow, request.input, request.settings, trace, evaluation,
        continuation=export_paused_state(trace.trace_id) if trace.status == "paused" else None,
    )
    return SimulateWorkflowResponse(trace=trace, evaluation=evaluation, run_id=run_id)


@router.post("/workflows/simulate/resume", response_model=SimulateWorkflowResponse)
async def resume_simulation_endpoint(request: ResumeSimulationRequest, user: ApprovedUser):
    budget = _Budget(settings.request_budget_seconds)
    if get_paused_settings(request.trace_id) is None:
        # Not in this process (e.g. another Lambda container paused it): rebuild from the stored run.
        await run_persistence.load_paused(user.id, request.trace_id)
    paused_info = get_paused_settings(request.trace_id)

    limit = min(settings.simulation_timeout_seconds, budget.remaining())
    try:
        trace = await asyncio.wait_for(
            resume_simulation(request.trace_id, request.node_id, request.decision, request.edge_target),
            timeout=limit,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail=f"Resuming timed out after {limit:g}s. Try mock mode or a smaller workflow.")
    except InvalidResumeError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except SimulationError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    evaluation = None
    if paused_info:
        resume_workflow, resume_settings = paused_info
        evaluation = await _evaluate(user, resume_workflow, trace, resume_settings, budget, check_limit=False)

    stored = await run_persistence.update_run(
        user.id, trace, evaluation,
        continuation=export_paused_state(trace.trace_id) if trace.status == "paused" else None,
    )
    return SimulateWorkflowResponse(trace=trace, evaluation=evaluation, run_id=trace.trace_id if stored else None)
