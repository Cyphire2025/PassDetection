"""Source-bound check selection and final CI gate validation."""
from __future__ import annotations

import datetime as dt
import json
import re

from ci_job_inputs import JOBS, REUSABLE_JOBS, classify_paths

SHA = re.compile(r"[0-9a-f]{40}")


def decide(source: str, event: str, paths: list[str] | None,
           current_fingerprints: dict[str, str], reuse: dict) -> dict:
    if not SHA.fullmatch(source) or event not in {"push", "pull_request", "workflow_dispatch"}:
        raise ValueError("Unsupported CI source or event")
    full = event == "workflow_dispatch"
    selected = set(JOBS) if full or paths is None else set(classify_paths(paths))
    # A stable check always validates workflow, policy, helper tests and docs.
    selected.add("backend-static-checks")
    decisions = {}
    for job in JOBS:
        state = "run" if job in selected else "unaffected"
        evidence = None
        if not full and state == "run" and job in REUSABLE_JOBS and job in reuse:
            evidence = reuse[job]
            if evidence.get("fingerprint") != current_fingerprints[job]:
                raise ValueError("Reuse evidence input mismatch")
            state = "reuse"
        decisions[job] = {"state": state, "fingerprint": current_fingerprints[job]}
        if evidence is not None:
            decisions[job]["evidence"] = evidence
    return {"version": 1, "source_revision": source, "event": event,
            "mode": "full" if full else "affected",
            "changed_path_count": None if paths is None else len(paths),
            "jobs": decisions}


def validate_gate(needs: dict, source: str, event: str,
                  current_fingerprints: dict[str, str], affected: set[str]) -> dict:
    if set(needs) != {"plan", *JOBS} or needs["plan"].get("result") != "success":
        raise ValueError("The CI planner and every check must be accounted for")
    plan = json.loads(needs["plan"].get("outputs", {}).get("plan", "null"))
    if (not isinstance(plan, dict) or plan.get("version") != 1
            or plan.get("source_revision") != source or plan.get("event") != event
            or plan.get("mode") != ("full" if event == "workflow_dispatch" else "affected")
            or set(plan.get("jobs", {})) != set(JOBS)):
        raise ValueError("CI plan does not bind this exact source and event")
    for job, decision in plan["jobs"].items():
        state = decision.get("state")
        result = needs[job].get("result")
        if decision.get("fingerprint") != current_fingerprints[job]:
            raise ValueError(f"{job}: inputs changed after planning")
        if state == "run":
            if result != "success":
                raise ValueError(f"{job}: required execution was {result}")
        elif state in {"reuse", "unaffected"}:
            if event == "workflow_dispatch" or result != "skipped":
                raise ValueError(f"{job}: Full or unexpectedly executed checks cannot be skipped")
            if state == "unaffected" and job in affected:
                raise ValueError(f"{job}: affected inputs cannot be marked unrelated")
            if state == "reuse":
                evidence = decision.get("evidence", {})
                if (job not in REUSABLE_JOBS
                        or evidence.get("fingerprint") != current_fingerprints[job]
                        or not SHA.fullmatch(evidence.get("source_revision", ""))
                        or type(evidence.get("run_id")) is not int
                        or type(evidence.get("job_id")) is not int):
                    raise ValueError(f"{job}: missing original successful-check evidence")
                completed = dt.datetime.fromisoformat(evidence.get("completed_at", "").replace("Z", "+00:00"))
                if (completed.tzinfo is None
                        or not dt.timedelta(0) <= dt.datetime.now(dt.timezone.utc) - completed <= dt.timedelta(hours=24)):
                    raise ValueError(f"{job}: original verification is expired or in the future")
        else:
            raise ValueError(f"{job}: unknown check disposition")
    return plan
