"""The ensemble and sweep reproducibility jobs are matrices of legs behind an aggregate job.

CI cannot run in the sandbox, so this reads the workflow. The aggregate keeps the original check name and must fail when
a leg fails or is skipped on a code change, and pass on a docs-only change.
"""

from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"
JOBS = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]

AGGREGATES = {"ensemble": "ensemble reproducibility", "sweeps": "sweep reproducibility"}


def _legs(job_id: str) -> dict:
    return JOBS[f"{job_id}-legs"]


def test_aggregate_keeps_the_check_name_and_needs_every_leg():
    for job_id, name in AGGREGATES.items():
        job = JOBS[job_id]
        assert job["name"] == name
        assert f"{job_id}-legs" in job["needs"]
        assert "changes" in job["needs"]


def test_aggregate_runs_always_and_checks_results_explicitly():
    for job_id in AGGREGATES:
        job = JOBS[job_id]
        assert job["if"].strip() == "always()"
        script = "\n".join(s.get("run", "") for s in job["steps"])
        assert "needs.changes.result" in str(job["steps"])
        assert "needs.changes.outputs.code" in str(job["steps"])
        assert f"needs.{job_id}-legs.result" in str(job["steps"])
        assert "exit 1" in script


def test_legs_are_a_matrix_that_expands_on_a_docs_only_change():
    for job_id in AGGREGATES:
        leg = _legs(job_id)
        assert "if" not in leg, "a skipped matrix job never expands its check names"
        assert leg["strategy"]["fail-fast"] is False
        assert len(leg["strategy"]["matrix"]["leg"]) >= 4
        for step in leg["steps"]:
            if step.get("uses", "").startswith("actions/checkout"):
                continue
            assert "needs.changes.outputs.code == 'true'" in step.get("if", ""), step
