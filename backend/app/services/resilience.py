"""Resilience drill: make each external step fail in turn and see what the workflow does (Task 60, B7).

Runs the workflow once as a baseline, then once per (step, failure kind) with that step made to fail. Mock mode only,
so it is deterministic and free. Each run gets one of three verdicts:

* handled: the workflow noticed and took a different route (for example a failure branch to a human review);
* ignored: the run finished on exactly the same path as the healthy one, so the failure passed through unnoticed;
* halted: the run stopped with an error.
"""
from app.models.workflow import NodeType, Workflow
from app.schemas.safety import DrillResult, ResilienceReport, ResilienceSummary
from app.schemas.simulation import FailureKind, HITLMode, InjectedFailure, LLMMode, SimulationSettings
from app.services.simulator import simulate

INJECTABLE = (NodeType.API, NodeType.DATABASE, NodeType.TOOL, NodeType.RAG, NodeType.LLM)
MAX_DRILL_STEPS = 30
_LABEL = {
    FailureKind.ERROR: "returns a server error",
    FailureKind.TIMEOUT: "times out",
    FailureKind.EMPTY: "returns nothing",
    FailureKind.MALFORMED: "returns malformed data",
}


def _undecided(trace) -> dict[str, str]:
    """Decisions that could not be made: the simulator followed every branch and warned (a real run would fail here)."""
    return {s.node_id: s.warnings[0] for s in trace.steps if s.node_type == "CONDITION" and any("following all edges" in w for w in s.warnings)}


def _ran(trace) -> list[str]:
    return [s.node_id for s in trace.steps if s.status.value in ("success", "error")]


async def run_drill(workflow: Workflow, input_data: dict, seed: int = 0) -> ResilienceReport:
    base_settings = SimulationSettings(llm_mode=LLMMode.MOCK, hitl_mode=HITLMode.AUTO_APPROVE, seed=seed)
    baseline = await simulate(workflow, input_data, base_settings)
    base_path = _ran(baseline)
    base_undecided = set(_undecided(baseline))
    notes: list[str] = []
    if baseline.status != "complete":
        return ResilienceReport(baseline_status=baseline.status, baseline_path=base_path, results=[], summary=ResilienceSummary(),
                                notes=["The workflow does not finish even without a failure, so there is nothing to compare against. Fix that first."])

    candidates = [n for n in workflow.nodes if n.type in INJECTABLE]
    reached = [n for n in candidates if n.id in base_path]
    not_reached = [n.id for n in candidates if n.id not in base_path]
    skipped = max(0, len(reached) - MAX_DRILL_STEPS)
    if not_reached:
        notes.append("Some steps did not run with this input, so they were not tested. Try an input that takes the other branch.")
    if skipped:
        notes.append(f"Only the first {MAX_DRILL_STEPS} steps were tested; {skipped} more were left out.")

    results: list[DrillResult] = []
    for node in reached[:MAX_DRILL_STEPS]:
        for kind in FailureKind:
            trace = await simulate(workflow, input_data, base_settings.model_copy(update={"inject": InjectedFailure(node_id=node.id, kind=kind)}))
            path = _ran(trace)
            error = next((s.error for s in trace.steps if s.error), None)
            if trace.status != "complete":
                failing = next((s for s in trace.steps if s.error), None)
                where = f" at “{failing.node_name}”" if failing and failing.node_id != node.id else ""
                verdict, detail = "halted", f"The run stopped{where}: {error or 'it did not finish'}."
            elif newly := {k: v for k, v in _undecided(trace).items() if k not in base_undecided}:
                node_id, why = next(iter(newly.items()))
                name = next(n.name for n in workflow.nodes if n.id == node_id)
                verdict, detail = "halted", f"The check “{name}” could not make its decision ({why.split(';')[0].rstrip('.')}), so a real run would stop there."
            elif set(path) != set(base_path):
                skipped_steps = [i for i in base_path if i not in path]
                new_steps = [i for i in path if i not in base_path]
                names = {n.id: n.name for n in workflow.nodes}
                parts = []
                if new_steps:
                    parts.append("now goes through " + ", ".join(f"“{names[i]}”" for i in new_steps))
                if skipped_steps:
                    parts.append("no longer reaches " + ", ".join(f"“{names[i]}”" for i in skipped_steps))
                verdict, detail = "handled", "The workflow noticed and " + " and ".join(parts) + "."
            else:
                verdict, detail = "ignored", "The run finished exactly as if nothing had gone wrong; the failure was passed along without being noticed."
            results.append(DrillResult(node_id=node.id, node_name=node.name, node_type=node.type.value, kind=kind,
                                       verdict=verdict, detail=f"When “{node.name}” {_LABEL[kind]}: {detail}", path=path, error=error))

    summary = ResilienceSummary(total=len(results), **{v: sum(1 for r in results if r.verdict == v) for v in ("handled", "ignored", "halted")})
    order = {"ignored": 0, "halted": 1, "handled": 2}
    results.sort(key=lambda r: (order[r.verdict], r.node_name))
    return ResilienceReport(baseline_status="complete", baseline_path=base_path, results=results, summary=summary,
                            not_reached=not_reached, skipped=skipped, notes=notes)
