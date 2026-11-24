"""Benchmark mock-mode simulation throughput (Task 49).

Usage (from backend/, with the project venv):

    .venv/Scripts/python.exe benchmarks/bench_simulation.py            # 100 cases per example
    .venv/Scripts/python.exe benchmarks/bench_simulation.py --cases 500 --json out.json

What is measured, per example workflow, over N cases (case i uses seed i, so branches vary):
  * simulate()           the engine itself, mock LLM, expression routing (no network, no I/O)
  * build_run_record()   the CPU part of saving a run (serialising trace + workflow to JSON-able dicts)
  * record size          bytes of the JSON that would be stored per case

NOT measured: Supabase round trips, real LLM calls, API Gateway/cold-start overhead. Those
dominate in production; see docs/AiFlow - Async Suite Runs Design.md section 3.
"""
import argparse
import asyncio
import json
import platform
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.models.workflow import Workflow  # noqa: E402
from app.schemas.simulation import ConditionMode, SimulationSettings  # noqa: E402
from app.services import run_persistence  # noqa: E402
from app.services.simulator import simulate  # noqa: E402

EXAMPLES = ROOT.parent / "examples"


def percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(pct / 100 * (len(ordered) - 1))))
    return ordered[index]


async def bench_workflow(path: Path, cases: int) -> dict:
    workflow = Workflow(**json.loads(path.read_text(encoding="utf-8")))
    sim_ms, record_ms, sizes, steps = [], [], [], []

    # Warm up imports / caches so the first case does not skew p95.
    await simulate(workflow, {}, SimulationSettings(condition_mode=ConditionMode.EXPRESSION, seed=-1))

    for i in range(cases):
        settings = SimulationSettings(condition_mode=ConditionMode.EXPRESSION, seed=i)
        t0 = time.perf_counter()
        trace = await simulate(workflow, {"case": i}, settings)
        t1 = time.perf_counter()
        record = run_persistence.build_run_record("bench-user", workflow, {"case": i}, settings, trace, None)
        t2 = time.perf_counter()
        if record is None:
            raise RuntimeError(f"{path.name}: run record exceeded the size cap")
        sim_ms.append((t1 - t0) * 1000)
        record_ms.append((t2 - t1) * 1000)
        sizes.append(len(json.dumps(record, default=str)))
        steps.append(len(trace.steps))

    total_ms = [a + b for a, b in zip(sim_ms, record_ms)]
    return {
        "example": str(path.relative_to(EXAMPLES)).replace("\\", "/"),
        "nodes": len(workflow.nodes),
        "avg_steps": round(statistics.mean(steps), 1),
        "sim_p50_ms": round(percentile(sim_ms, 50), 3),
        "sim_p95_ms": round(percentile(sim_ms, 95), 3),
        "record_p95_ms": round(percentile(record_ms, 95), 3),
        "case_p95_ms": round(percentile(total_ms, 95), 3),
        "case_max_ms": round(max(total_ms), 3),
        "record_kb_p95": round(percentile(sizes, 95) / 1024, 1),
        "cases_per_sec": round(1000 / statistics.mean(total_ms), 1),
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=int, default=100)
    parser.add_argument("--json", type=Path, help="also write the results to this file")
    args = parser.parse_args()

    files = sorted(EXAMPLES.rglob("*.json"))
    results = [await bench_workflow(f, args.cases) for f in files]

    print(f"python {platform.python_version()} on {platform.platform()} - {args.cases} cases per example (mock mode)\n")
    cols = ["example", "nodes", "avg_steps", "sim_p50_ms", "sim_p95_ms", "record_p95_ms", "case_p95_ms", "record_kb_p95", "cases_per_sec"]
    widths = [max(len(c), *(len(str(r[c])) for r in results)) for c in cols]
    print("  ".join(c.ljust(w) for c, w in zip(cols, widths)))
    for r in results:
        print("  ".join(str(r[c]).ljust(w) for c, w in zip(cols, widths)))

    worst = max(results, key=lambda r: r["case_p95_ms"])
    print(f"\nworst case p95: {worst['case_p95_ms']} ms ({worst['example']})")
    if args.json:
        args.json.write_text(json.dumps(results, indent=2), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
