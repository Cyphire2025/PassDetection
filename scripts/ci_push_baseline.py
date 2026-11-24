"""Qualify exact-source completed run history before routine check reuse."""
from __future__ import annotations

import datetime as dt

from ci_gate_policy import SHA


def qualified_push_base(api, repository: str, workflow_id: int, revision: str, branch: str) -> bool:
    """Use the latest exact-source CI gate, including an explicit Full run.

    Production publication happens after qualification and does not replace its
    result. A later failed, cancelled, missing or ambiguous gate cannot disappear
    behind a query filtered to successful runs. Missing gates are observed at the
    completed run's update time, so a subsequently passing Full can supersede an
    earlier cancelled duplicate push.
    """
    if (not isinstance(revision, str) or not SHA.fullmatch(revision) or revision == "0" * 40
            or not isinstance(branch, str) or not branch):
        return False
    now = dt.datetime.now(dt.timezone.utc)

    def timestamp(value):
        try:
            result = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
            return result if result.tzinfo and result <= now else None
        except (AttributeError, TypeError, ValueError):
            return None

    response = api(f"/repos/{repository}/actions/workflows/{workflow_id}/runs"
                   f"?head_sha={revision}&status=completed&per_page=20")
    runs = response.get("workflow_runs")
    if (not isinstance(runs, list) or len(runs) > 20
            or type(response.get("total_count")) is not int
            or response["total_count"] != len(runs)):
        return False
    observations = []
    for run in runs:
        if not isinstance(run, dict):
            return False
        if (run.get("head_sha") != revision or run.get("workflow_id") != workflow_id
                or run.get("path") != ".github/workflows/ci.yml"
                or run.get("event") not in {"push", "workflow_dispatch"} or run.get("head_branch") != branch
                or run.get("repository", {}).get("full_name") != repository
                or run.get("status") != "completed"
                or type(run.get("id")) is not int or run["id"] <= 0
                or type(run.get("run_attempt")) is not int or run["run_attempt"] <= 0):
            continue
        created, updated = timestamp(run.get("created_at")), timestamp(run.get("updated_at"))
        if created is None or updated is None or updated < created:
            return False
        jobs = api(f"/repos/{repository}/actions/runs/{run['id']}/attempts/"
                   f"{run['run_attempt']}/jobs?per_page=100")
        rows = jobs.get("jobs")
        if (not isinstance(rows, list) or type(jobs.get("total_count")) is not int
                or jobs["total_count"] != len(rows) or len(rows) > 100):
            return False
        gates = [job for job in rows if isinstance(job, dict) and job.get("name") == "Required CI checks"]
        observed, passed = updated, False
        if len(gates) == 1:
            gate = gates[0]
            completed = timestamp(gate.get("completed_at"))
            if (gate.get("status") == "completed" and completed is not None and created <= completed <= updated
                    and gate.get("run_id") == run["id"] and gate.get("run_attempt") == run["run_attempt"]
                    and gate.get("head_sha") == revision and type(gate.get("id")) is int and gate["id"] > 0):
                observed, passed = completed, gate.get("conclusion") == "success"
        observations.append((observed, passed))
    if not observations:
        return False
    latest = max(stamp for stamp, _ in observations)
    return all(passed for stamp, passed in observations if stamp == latest)
