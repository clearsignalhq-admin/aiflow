"""Compare two runs of the same test suite (Task 58).

Answers "what got better or worse between these runs, and what changed that could explain it?":

* every test case is classified: regressed (passed, now fails), fixed, still failing, unchanged, added,
  removed, or incomplete (a run did not reach it);
* for cases that ran in both, which checks flipped, whether the path through the workflow changed, and whether
  the output changed;
* a diff of the two workflow snapshots (steps added, removed and edited, edges added and removed), and of the
  test cases themselves, so a regression can be traced to an edit;
* coverage movement, and warnings when the two runs are not directly comparable (different mode, seed,
  edited cases, real-model variation).

Pure functions over stored rows: no database access here.
"""
import json
from typing import Any, Optional

from app.schemas.suites import (
    AssertionChange,
    CaseComparison,
    CoverageChange,
    EdgeChange,
    FieldChange,
    NodeChange,
    RunComparison,
    RunSide,
    WorkflowDiff,
)
from app.services.suite_runner import build_report

_ORDER = {"regressed": 0, "fixed": 1, "still_failing": 2, "incomplete": 3, "added": 4, "removed": 5, "unchanged": 6}
_MAX_TEXT = 300
_MAX_ASSERTION_CHANGES = 20


def _canon(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _short(value: Any) -> Any:
    """Keep a diff readable: long text and nested values are cut off."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    text = value if isinstance(value, str) else _canon(value)
    return text if len(text) <= _MAX_TEXT else text[: _MAX_TEXT - 1] + "…"


# ── Workflow snapshots ───────────────────────────────────────────────────────

def diff_workflows(base: dict[str, Any], head: dict[str, Any]) -> WorkflowDiff:
    """Steps and edges that differ between two stored workflow snapshots (positions are ignored)."""
    a = {n["id"]: n for n in base.get("nodes", [])}
    b = {n["id"]: n for n in head.get("nodes", [])}
    name_of = {**{i: n.get("name", i) for i, n in a.items()}, **{i: n.get("name", i) for i, n in b.items()}}

    nodes: list[NodeChange] = []
    for node_id in [i for i in b if i not in a]:
        nodes.append(NodeChange(node_id=node_id, name=b[node_id].get("name", node_id), change="added"))
    for node_id in [i for i in a if i not in b]:
        nodes.append(NodeChange(node_id=node_id, name=a[node_id].get("name", node_id), change="removed"))
    for node_id in [i for i in a if i in b]:
        fields: list[FieldChange] = []
        for key in ("name", "type"):
            if a[node_id].get(key) != b[node_id].get(key):
                fields.append(FieldChange(field=key, before=a[node_id].get(key), after=b[node_id].get(key)))
        ca, cb = a[node_id].get("config") or {}, b[node_id].get("config") or {}
        for key in sorted(set(ca) | set(cb)):
            if _canon(ca.get(key)) != _canon(cb.get(key)):
                fields.append(FieldChange(field=f"config.{key}", before=_short(ca.get(key)), after=_short(cb.get(key))))
        for key in ("input_schema", "output_schema"):
            if _canon(a[node_id].get(key)) != _canon(b[node_id].get(key)):
                fields.append(FieldChange(field=key, before=_short(a[node_id].get(key)), after=_short(b[node_id].get(key))))
        if fields:
            nodes.append(NodeChange(node_id=node_id, name=b[node_id].get("name", node_id), change="modified", fields=fields))

    def edge_set(wf: dict[str, Any]) -> set[tuple[str, str, Optional[str]]]:
        return {(e["source"], e["target"], e.get("condition") or None) for e in wf.get("edges", [])}

    ea, eb = edge_set(base), edge_set(head)

    def edge(change: str, key: tuple[str, str, Optional[str]]) -> EdgeChange:
        return EdgeChange(source=key[0], target=key[1], label=key[2], change=change,
                          source_name=name_of.get(key[0], key[0]), target_name=name_of.get(key[1], key[1]))

    edges = [edge("added", k) for k in sorted(eb - ea, key=str)] + [edge("removed", k) for k in sorted(ea - eb, key=str)]
    return WorkflowDiff(nodes=nodes, edges=edges, changed=bool(nodes or edges))


# ── One run ──────────────────────────────────────────────────────────────────

def _side(run: dict[str, Any], results: list[dict[str, Any]]) -> RunSide:
    report = build_report(run["workflow"], run["case_count"], results)
    return RunSide(
        id=run["id"], created_at=run["created_at"], status=run["status"], llm_mode=run.get("llm_mode") or "mock",
        seed=run["seed"], case_count=run["case_count"], completed=report.completed, passed=report.passed,
        failed=report.failed, errors=report.errors, pass_rate=report.pass_rate, llm_calls=report.llm_calls,
        total_duration_ms=sum(int(r.get("duration_ms") or 0) for r in results),
    )


# ── One case ─────────────────────────────────────────────────────────────────

def _classify(base: Optional[dict[str, Any]], head: Optional[dict[str, Any]], in_base: bool, in_head: bool) -> str:
    if in_base and not in_head:
        return "removed"
    if in_head and not in_base:
        return "added"
    if base is None or head is None:
        return "incomplete"
    was, now = base["status"] == "passed", head["status"] == "passed"
    if was and not now:
        return "regressed"
    if not was and now:
        return "fixed"
    return "unchanged" if was else "still_failing"


def _assertion_changes(base: dict[str, Any], head: dict[str, Any], same_definition: bool) -> list[AssertionChange]:
    """Checks whose outcome differs. Matched by position when the case was not edited, otherwise by label."""
    b_list, h_list = base.get("assertion_results") or [], head.get("assertion_results") or []
    changes: list[AssertionChange] = []
    if same_definition:
        pairs = [(b_list[i] if i < len(b_list) else None, h_list[i] if i < len(h_list) else None) for i in range(max(len(b_list), len(h_list)))]
    else:
        by_label = {x["label"]: x for x in b_list}
        pairs = [(by_label.pop(x["label"], None), x) for x in h_list] + [(x, None) for x in by_label.values()]
    for b, h in pairs:
        if b is not None and h is not None and b["passed"] == h["passed"]:
            continue
        ref = h or b
        changes.append(AssertionChange(
            label=ref["label"], type=ref["type"],
            base_passed=b["passed"] if b else None, head_passed=h["passed"] if h else None,
            base_message=b["message"] if b else None, head_message=h["message"] if h else None,
        ))
    return changes[:_MAX_ASSERTION_CHANGES]


def _compare_case(case_id: str, base_case: Optional[dict[str, Any]], head_case: Optional[dict[str, Any]],
                  base: Optional[dict[str, Any]], head: Optional[dict[str, Any]]) -> CaseComparison:
    def definition(case: Optional[dict[str, Any]]) -> str:
        return _canon({k: (case or {}).get(k) for k in ("input", "assertions", "seed")})

    change = _classify(base, head, base_case is not None, head_case is not None)
    edited = base_case is not None and head_case is not None and definition(base_case) != definition(head_case)
    out = CaseComparison(
        case_id=case_id, case_name=(head_case or base_case or {}).get("name", case_id), change=change,
        base_status=base["status"] if base else None, head_status=head["status"] if head else None,
        definition_changed=edited,
        base_error=base.get("error") if base else None, head_error=head.get("error") if head else None,
    )
    if base is not None and head is not None:
        bp, hp = base.get("path") or [], head.get("path") or []
        out.path_changed = bp != hp
        out.nodes_added = [n for n in dict.fromkeys(hp) if n not in bp]
        out.nodes_removed = [n for n in dict.fromkeys(bp) if n not in hp]
        out.output_changed = _canon(base.get("output")) != _canon(head.get("output"))
        out.assertion_changes = _assertion_changes(base, head, same_definition=not edited)
        out.duration_delta_ms = int(head.get("duration_ms") or 0) - int(base.get("duration_ms") or 0)
        out.llm_calls_delta = int(head.get("llm_calls") or 0) - int(base.get("llm_calls") or 0)
    return out


# ── Two runs ─────────────────────────────────────────────────────────────────

def compare_runs(base_run: dict[str, Any], head_run: dict[str, Any],
                 base_results: list[dict[str, Any]], head_results: list[dict[str, Any]]) -> RunComparison:
    """``base`` is the earlier run being compared against; ``head`` is the one you are looking at."""
    base_by = {r["case_id"]: r["result"] if "result" in r else r for r in base_results}
    head_by = {r["case_id"]: r["result"] if "result" in r else r for r in head_results}
    base_cases = {c["id"]: c for c in base_run["cases"]}
    head_cases = {c["id"]: c for c in head_run["cases"]}
    base_flat, head_flat = list(base_by.values()), list(head_by.values())

    ids = list(dict.fromkeys([*head_cases, *base_cases]))
    cases = sorted(
        (_compare_case(i, base_cases.get(i), head_cases.get(i), base_by.get(i), head_by.get(i)) for i in ids),
        key=lambda c: _ORDER[c.change],
    )
    counts = {k: sum(1 for c in cases if c.change == k) for k in _ORDER}

    base_side, head_side = _side(base_run, base_flat), _side(head_run, head_flat)
    delta = None
    if base_side.pass_rate is not None and head_side.pass_rate is not None:
        delta = round(head_side.pass_rate - base_side.pass_rate, 4)

    base_cov = build_report(base_run["workflow"], base_run["case_count"], base_flat).coverage
    head_cov = build_report(head_run["workflow"], head_run["case_count"], head_flat).coverage
    visited_b = {n for n, c in base_cov.node_visits.items() if c}
    visited_h = {n for n, c in head_cov.node_visits.items() if c}
    coverage = CoverageChange(
        nodes_newly_visited=sorted(visited_h - visited_b), nodes_no_longer_visited=sorted(visited_b - visited_h),
        edges_newly_taken=sorted(set(head_cov.edges_taken) - set(base_cov.edges_taken)),
        edges_no_longer_taken=sorted(set(base_cov.edges_taken) - set(head_cov.edges_taken)),
    )

    workflow = diff_workflows(base_run["workflow"], head_run["workflow"])
    verdict = "regression" if counts["regressed"] else "improvement" if counts["fixed"] else "no_change"

    warnings: list[str] = []
    if base_side.llm_mode != head_side.llm_mode:
        warnings.append("One run used the real AI model and the other simulated answers, so differences may not come from the workflow.")
    elif head_side.llm_mode == "real":
        warnings.append("Both runs used the real AI model. Some changes can be ordinary variation in its answers; run again to check.")
    elif base_side.seed != head_side.seed:
        warnings.append(f"The runs used different seeds ({base_side.seed} and {head_side.seed}), so the simulated data differs.")
    edited = sum(1 for c in cases if c.definition_changed)
    if edited:
        warnings.append(f"{edited} test case{'s were' if edited != 1 else ' was'} edited between the runs, so their results are not directly comparable.")
    if counts["added"] or counts["removed"]:
        warnings.append(f"The suites differ: {counts['added']} case(s) added and {counts['removed']} removed since the earlier run.")
    if counts["incomplete"] or base_side.status != "complete" or head_side.status != "complete":
        warnings.append("At least one run did not finish every case; only cases that ran in both are compared.")
    if (verdict == "regression" and base_side.llm_mode == head_side.llm_mode == "mock" and base_side.seed == head_side.seed
            and not workflow.changed and not edited):
        warnings.append("Nothing in the workflow or the test cases changed between these runs, yet results differ. Check for something outside the workflow (for example a change to the application itself).")

    return RunComparison(
        base=base_side, head=head_side, verdict=verdict,
        summary={**counts, "pass_rate_delta": delta}, cases=cases, workflow=workflow, coverage=coverage, warnings=warnings,
    )
