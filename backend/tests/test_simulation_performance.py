"""Loose regression guard for mock-mode simulation speed (Task 49).

Measured on a developer machine: ~0.3 ms per case for the largest example (see
backend/benchmarks/bench_simulation.py). The bound below is ~50x slower than that on purpose:
it only exists to catch accidental quadratic behaviour or I/O sneaking into the engine,
not to flake on a slow CI runner.
"""
import json
import time
from pathlib import Path

import pytest

from app.models.workflow import Workflow
from app.schemas.simulation import ConditionMode, SimulationSettings
from app.services.simulator import simulate

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "complex" / "ai-research-agent.json"
CASES = 100
BUDGET_SECONDS = 2.0     # ~20 ms per case allowed vs ~0.3 ms measured


@pytest.mark.asyncio
async def test_mock_simulation_of_the_largest_example_stays_fast():
    workflow = Workflow(**json.loads(EXAMPLE.read_text(encoding="utf-8")))
    started = time.perf_counter()
    for seed in range(CASES):
        trace = await simulate(workflow, {"case": seed}, SimulationSettings(condition_mode=ConditionMode.EXPRESSION, seed=seed))
        assert trace.status == "complete"
    elapsed = time.perf_counter() - started
    assert elapsed < BUDGET_SECONDS, f"{CASES} cases took {elapsed:.2f}s (budget {BUDGET_SECONDS}s)"
