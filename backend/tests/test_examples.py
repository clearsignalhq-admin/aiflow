"""The example workflows are what a new user sees first, so they are held to the standard the product teaches (Task 67).

Every example must validate, simulate cleanly, pass the design checks and export to valid code. One is the exception on
purpose: Supply Chain Monitor keeps its design findings so the guide and videos can demonstrate the checks on it.
"""
import ast
import glob
import io
import json
import os
import re
import zipfile

import pytest

from app.models.workflow import NodeType, Workflow
from app.schemas.simulation import SimulationSettings
from app.services.exporters import export_zip
from app.services.fixes import suggest_fixes
from app.services.langgraph_exporter import ExportError
from app.services.injection_exposure import analyse_exposure
from app.services.linter import lint_workflow
from app.services.patching import apply_changes
from app.services.resilience import run_drill
from app.services.simulator import simulate
from app.services.validator import validate_workflow

EXAMPLES = os.path.join(os.path.dirname(__file__), "..", "..", "examples")
PATHS = sorted(glob.glob(os.path.join(EXAMPLES, "*", "*.json")))
TEACHING = "supply-chain-monitor"                      # deliberately left with findings
IDS = [os.path.relpath(p, EXAMPLES).replace("\\", "/") for p in PATHS]


def raw(path):
    return json.load(open(path, encoding="utf-8"))


def load(path) -> Workflow:
    return Workflow(**raw(path))


def teaching(path) -> bool:
    return os.path.basename(path).startswith(TEACHING)


def test_there_are_examples_in_every_tier_and_no_stray_files():
    assert len(PATHS) >= 12
    assert {os.path.basename(os.path.dirname(p)) for p in PATHS} == {"easy", "medium", "complex"}
    assert glob.glob(os.path.join(EXAMPLES, "*.json")) == []                           # nothing outside the tier folders (the picker would never show it)


def test_ids_and_names_are_unique():
    ws = [raw(p) for p in PATHS]
    assert len({w["id"] for w in ws}) == len(ws)
    assert len({w["name"] for w in ws}) == len(ws)


@pytest.mark.parametrize("path", PATHS, ids=IDS)
class TestEveryExample:
    def test_metadata_is_complete_and_matches_its_folder(self, path):
        w = raw(path)
        meta = w["metadata"]
        assert meta["difficulty"] == os.path.basename(os.path.dirname(path))
        assert len(w["description"]) >= 60 and meta["industry"] and meta["tags"]
        assert isinstance(meta["sample_input"], dict) and meta["sample_input"]         # Simulate has something to start with

    def test_validates_without_errors_or_warnings(self, path):
        result = validate_workflow(load(path))
        assert result.valid and result.errors == [] and result.warnings == []

    @pytest.mark.asyncio
    async def test_simulates_cleanly_on_every_seed(self, path):
        w = load(path)
        for seed in range(6):
            trace = await simulate(w, w.metadata["sample_input"], SimulationSettings(seed=seed))
            assert trace.status == "complete", (seed, trace.steps[-1].error)
            assert [x for s in trace.steps for x in s.warnings] == [], seed           # every decision decides; nothing follows "all edges"

    def test_design_findings(self, path):
        found = lint_workflow(load(path)).findings
        if teaching(path):
            assert {f.rule_id for f in found} == {"no-failure-branch"} and len(found) == 4
        else:
            assert found == []

    def test_injection_exposure_is_never_high_unless_it_is_the_teaching_example(self, path):
        severities = {x.severity for x in analyse_exposure(load(path)).exposures}
        assert ("high" in severities) == teaching(path)

    def test_applying_every_suggested_fix_leaves_no_findings(self, path):
        """The fixes must never create new problems (a review added after a write used to be flagged as an approval too late)."""
        w = load(path)
        fixed = apply_changes(w, suggest_fixes(w))
        assert fixed.skipped == []
        assert lint_workflow(fixed.workflow).findings == []

    @pytest.mark.asyncio
    async def test_no_outside_step_fails_silently(self, path):
        w = load(path)
        report = await run_drill(w, w.metadata["sample_input"])
        outside = [r for r in report.results if r.node_type in ("API", "DATABASE", "TOOL")]
        silent = [r for r in outside if r.verdict == "ignored"]
        assert (len(silent) > 0) == teaching(path)

    def test_no_secrets_are_written_into_the_workflow(self, path):
        text = open(path, encoding="utf-8").read()
        assert not re.search(r"sk-[A-Za-z0-9]{10,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{20,}", text)
        for n in load(path).nodes:
            for key, value in (n.config.get("headers") or {}).items():
                if key.lower() in ("authorization", "x-api-key"):
                    assert "env:" in str(value), (n.id, key)                           # credentials are references, never values
            conn = n.config.get("connection")
            assert conn is None or str(conn).startswith("env:"), n.id

    def test_every_decision_has_labelled_branches(self, path):
        w = load(path)
        for n in w.nodes:
            if n.type == NodeType.CONDITION:
                labels = [e.condition for e in w.edges if e.source == n.id]
                assert len(labels) >= 2 and all(labels), n.id

    @pytest.mark.parametrize("target", ["langgraph", "python", "mcp"])
    def test_exports_to_valid_python(self, path, target):
        w = load(path)
        if target == "mcp" and not any(n.type in (NodeType.TOOL, NodeType.API, NodeType.DATABASE, NodeType.RAG) for n in w.nodes):
            with pytest.raises(ExportError, match="nothing to expose"):                  # a model-only workflow has no tools to offer
                export_zip(w, target)
            return
        _, data = export_zip(w, target)
        sources = [n for n in zipfile.ZipFile(io.BytesIO(data)).namelist() if n.endswith(".py")]
        assert sources
        for name in sources:
            ast.parse(zipfile.ZipFile(io.BytesIO(data)).read(name).decode("utf-8"), filename=name)

    def test_layout_has_no_overlapping_steps(self, path):
        nodes = load(path).nodes
        for i, a in enumerate(nodes):
            for b in nodes[i + 1:]:
                assert abs(a.position.x - b.position.x) >= 100 or abs(a.position.y - b.position.y) >= 50, (a.id, b.id)


def test_the_teaching_example_says_so():
    path = next(p for p in PATHS if teaching(p))
    w = raw(path)
    assert "deliberately" in w["description"] and "try-the-checks" in w["metadata"]["tags"]


def test_the_safe_by_design_example_has_a_review_between_the_model_and_the_payment():
    w = load(next(p for p in PATHS if p.endswith("refund-request.json")))
    exposure = analyse_exposure(w).exposures
    assert [(x.name, x.severity) for x in exposure] == [("Classify Request", "low")]
    assert all(s.gated for s in exposure[0].sinks)
