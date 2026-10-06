"""Plan affected checks and enforce an honest, always-present release gate.

Automatic runs may reuse bounded, server-verified successful checks with
identical Git inputs. Explicit manual runs always execute every check afresh.
No cache entry, skipped job, or prior image can qualify a Full deployment.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

from ci_job_inputs import (
    JOBS,
    REUSABLE_JOBS,
    classify_paths,
    fingerprints,
    read_git_tree,
)

ROOT = Path(__file__).resolve().parents[1]
SHA = re.compile(r"[0-9a-f]{40}")
JOB_NAMES = {
    "backend-static-checks": "Backend — Lint & Compile Check",
    "backend-dependency-audit": "Backend — Dependency Audit",
    "backend-test": "Backend — Tests",
    "backend-service-integration": "Backend - PostgreSQL, Redis, Private S3 & Celery",
    "backend-migration-rehearsal": "Backend - Populated PostgreSQL Restore & Upgrade",
    "frontend-lint": "Frontend — Lint & Type Check",
    "frontend-browser": "Frontend - Browser Journeys",
    "connector-windows": "MCP Connector — Windows Tests & Wheel",
    "docker-build": "Docker — Build Verification",
}

PROVENANCE_PATH = ROOT / "outputs" / "ci-provenance" / "ci-provenance.json"


def git(*arguments: str) -> str:
    return subprocess.check_output(
        ["git", *arguments], cwd=ROOT, encoding="utf-8", errors="strict",
        stderr=subprocess.DEVNULL,
    ).strip()


def ancestor(base: str, head: str) -> bool:
    if not SHA.fullmatch(base) or not SHA.fullmatch(head):
        return False
    return subprocess.run(
        ["git", "merge-base", "--is-ancestor", base, head], cwd=ROOT,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
    ).returncode == 0


def changed_paths(base: str, source: str) -> list[str]:
    if not SHA.fullmatch(base) or not SHA.fullmatch(source) or base == "0" * 40:
        raise ValueError("No complete comparison base")
    output = subprocess.check_output(
        ["git", "diff", "--name-only", "--no-renames", "-z", base, source, "--"],
        cwd=ROOT, stderr=subprocess.DEVNULL,
    )
    return [part.decode("utf-8", errors="strict") for part in output.split(b"\0") if part]


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


def collection_digest(nodeids: list[str]) -> str:
    return hashlib.sha256("\n".join(sorted(nodeids)).encode("utf-8")).hexdigest()


def verify_shards(directory: Path, count: int) -> None:
    reports = sorted(directory.glob("ci-shard-*.json"))
    if len(reports) != count or count < 1:
        raise ValueError("Every backend shard must supply its collection report")
    selections: list[str] = []
    indexes = set()
    collections = set()
    for path in reports:
        report = json.loads(path.read_text("utf-8"))
        index = report["shard_index"]
        if (type(index) is not int or not 1 <= index <= count or index in indexes
                or report.get("schema_version") != 1
                or report["shard_count"] != count or type(report["collection_count"]) is not int
                or report["collection_count"] < 1
                or not re.fullmatch(r"[0-9a-f]{64}", report["collection_sha256"])):
            raise ValueError("Backend shard identity or collection is inconsistent")
        selected = report["selected_nodeids"]
        if not isinstance(selected, list) or not selected or any(not isinstance(x, str) for x in selected):
            raise ValueError("Backend shard selection must contain collected test IDs")
        indexes.add(index)
        selections.extend(selected)
        collections.add((report["collection_count"], report["collection_sha256"]))
        coverage = directory / f".coverage.shard-{index}"
        if not coverage.is_file() or coverage.stat().st_size == 0:
            raise ValueError("Every backend shard must supply coverage data")
    if (len(collections) != 1 or len(set(selections)) != len(selections)
            or (len(selections), collection_digest(selections)) not in collections):
        raise ValueError("Backend shards duplicated or omitted collected tests")
    print(f"All {len(selections)} collected tests are assigned exactly once across {count} shards.")


def write_summary(plan: dict, title: str) -> None:
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if not target:
        return
    lines = [f"## {title}", "", f"Source: `{plan['source_revision']}`; mode: **{plan['mode']}**.",
             "", "| Check | Decision | Evidence |", "|---|---|---|"]
    for job, value in plan["jobs"].items():
        evidence = value.get("evidence")
        detail = "Required on this revision" if value["state"] == "run" else "Inputs unaffected"
        if evidence:
            # URLs are built from numeric API identities, never from changed file text.
            url = (f"https://github.com/{os.environ['GITHUB_REPOSITORY']}/actions/runs/"
                   f"{evidence['run_id']}/job/{evidence['job_id']}")
            detail = f"[Identical inputs; original successful check]({url}), {evidence['completed_at']}"
        lines.append(f"| {JOB_NAMES[job]} | {value['state']} | {detail} |")
    lines += ["", ("Reuse is limited to recent successful checks with identical Git inputs and CI rules. "
              "Dependency audits and image qualification remain fresh when selected. "
              "Full always executes every check; no prior images are promoted."), ""]
    with Path(target).open("a", encoding="utf-8") as stream:
        stream.write("\n".join(lines))


def event_paths(source: str, event: str, payload: dict) -> list[str] | None:
    paths = None
    try:
        if event == "pull_request":
            paths = changed_paths(payload["pull_request"]["base"]["sha"], source)
        elif event == "push":
            paths = changed_paths(payload["before"], source)
    except (KeyError, ValueError, UnicodeError, subprocess.SubprocessError):
        # Missing histories, first pushes and unusual names select every check.
        pass
    return paths


def qualified_push_base(api, repository: str, workflow_id: int, revision: str) -> bool:
    """Never let a docs-only push hide unresolved checks on its predecessor."""
    if not SHA.fullmatch(revision) or revision == "0" * 40:
        return False
    response = api(f"/repos/{repository}/actions/workflows/{workflow_id}/runs"
                   f"?head_sha={revision}&event=push&status=success&per_page=5")
    for run in response["workflow_runs"]:
        if (run.get("head_sha") != revision or run.get("workflow_id") != workflow_id
                or run.get("path") != ".github/workflows/ci.yml" or run.get("event") != "push"
                or run.get("repository", {}).get("full_name") != repository
                or run.get("status") != "completed" or run.get("conclusion") != "success"
                or type(run.get("id")) is not int or type(run.get("run_attempt")) is not int):
            continue
        jobs = api(f"/repos/{repository}/actions/runs/{run['id']}/attempts/"
                   f"{run['run_attempt']}/jobs?per_page=100")
        gates = [job for job in jobs["jobs"] if job.get("name") == "Required CI checks"]
        if (jobs.get("total_count") == len(jobs["jobs"]) and len(gates) == 1
                and gates[0].get("status") == "completed" and gates[0].get("conclusion") == "success"):
            return True
    return False


def run_provenance(context: dict, run: dict, payload: dict, tree: str) -> dict:
    """Bind the checkout to immutable event inputs, never the API's live PR object."""
    if (not SHA.fullmatch(tree)
            or run.get("id") != context["run_id"]
            or run.get("run_attempt") != context["run_attempt"]
            or run.get("event") != context["event"]
            or run.get("path") != ".github/workflows/ci.yml"
            or run.get("repository", {}).get("id") != context["repository_id"]
            or run.get("repository", {}).get("full_name") != context["repository"]
            or type(context["workflow_id"]) is not int
            or not SHA.fullmatch(context["head_sha"])
            or not SHA.fullmatch(context["source_sha"])):
        raise ValueError("Run identity cannot be bound to the checked-out inputs")
    if context["event"] == "pull_request":
        if (payload["pull_request"]["head"]["sha"] != context["head_sha"]
                or context["pull_request"]["head_ref"] != context["head_branch"]):
            raise ValueError("Run head differs from its original pull request event")
    elif context["event"] != "push" or context["source_sha"] != context["head_sha"]:
        raise ValueError("Only exact automatic push or pull request inputs are reusable")
    return {"schema_version": 1, "tree_sha": tree,
            **{key: value for key, value in context.items() if key != "workflow_path"}}


def make_plan() -> dict:
    PROVENANCE_PATH.unlink(missing_ok=True)
    event = os.environ["GITHUB_EVENT_NAME"]
    source = os.environ["GITHUB_SHA"]
    if not SHA.fullmatch(source) or git("rev-parse", "HEAD") != source:
        raise ValueError("Checkout differs from the selected workflow revision")
    payload = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text("utf-8"))
    if event == "workflow_dispatch":
        selected = payload.get("inputs", {}).get("expected_revision")
        if selected and selected != source:
            raise ValueError("The manually selected main commit was superseded")
    paths = event_paths(source, event, payload)
    tree_cache = {source: read_git_tree(ROOT, source)}

    def inputs_at(revision, job):
        if revision not in tree_cache:
            tree_cache[revision] = read_git_tree(ROOT, revision)
        return fingerprints(tree_cache[revision])[job]

    current = fingerprints(tree_cache[source])
    reuse = {}
    push_base_verified = event != "push"
    if event in {"pull_request", "push"} and os.environ.get("GH_TOKEN"):
        from ci_success_reuse import GitHubAPI, discover_reuse

        try:
            repository = os.environ["GITHUB_REPOSITORY"]
            api = GitHubAPI(repository, token=os.environ["GH_TOKEN"])
            run_id = int(os.environ["GITHUB_RUN_ID"])
            run = api(f"/repos/{repository}/actions/runs/{run_id}")
            if event == "push":
                push_base_verified = qualified_push_base(
                    api, repository, run["workflow_id"], payload.get("before", ""))
            context = {
                "repository": repository, "repository_id": int(os.environ["GITHUB_REPOSITORY_ID"]),
                "workflow_id": run["workflow_id"], "workflow_path": ".github/workflows/ci.yml",
                "event": event, "head_branch": run["head_branch"], "head_sha": run["head_sha"],
                "source_sha": source, "run_id": run_id,
                "run_attempt": int(os.environ["GITHUB_RUN_ATTEMPT"]),
            }
            if event == "pull_request":
                pr = payload["pull_request"]
                context["pull_request"] = {
                    "number": payload["number"], "base_sha": pr["base"]["sha"],
                    "base_ref": pr["base"]["ref"], "head_ref": pr["head"]["ref"],
                    "head_repo_id": pr["head"]["repo"]["id"],
                }
            receipt = run_provenance(context, run, payload, git("rev-parse", source + "^{tree}"))
            PROVENANCE_PATH.parent.mkdir(parents=True, exist_ok=True)
            PROVENANCE_PATH.write_text(json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8")
            eligible = {job: current[job] for job in REUSABLE_JOBS}
            reuse = discover_reuse(
                context, eligible, JOB_NAMES, api=api, fingerprint_at=inputs_at,
                ancestor=ancestor, tree_at=lambda revision: git("rev-parse", revision + "^{tree}"),
            )
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
            print("Prior verification could not be established; selected checks will run fresh.")
    if not push_base_verified:
        paths = None
    return decide(source, event, paths, current, reuse)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "gate", "verify-shards"))
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--count", type=int, default=4)
    args = parser.parse_args()
    if args.action == "verify-shards":
        verify_shards(args.directory, args.count)
        return
    if args.action == "plan":
        plan = make_plan()
        with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as stream:
            stream.write(f"provenance={'true' if PROVENANCE_PATH.is_file() else 'false'}\n")
            stream.write("plan=" + json.dumps(plan, separators=(",", ":")) + "\n")
            stream.writelines(f"{job}={'true' if value['state'] == 'run' else 'false'}\n"
                              for job, value in plan["jobs"].items())
        write_summary(plan, "Check plan")
    else:
        source = os.environ["GITHUB_SHA"]
        if git("rev-parse", "HEAD") != source:
            raise ValueError("Gate checkout differs from workflow revision")
        event = os.environ["GITHUB_EVENT_NAME"]
        payload = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text("utf-8"))
        paths = event_paths(source, event, payload)
        needs = json.loads(os.environ["CI_NEEDS"])
        planned = json.loads(needs.get("plan", {}).get("outputs", {}).get("plan", "{}"))
        affected = set(JOBS) if paths is None or planned.get("changed_path_count") is None else set(classify_paths(paths))
        affected.add("backend-static-checks")
        plan = validate_gate(needs, source, event,
                             fingerprints(read_git_tree(ROOT, source)), affected)
        write_summary(plan, "Required checks passed")
        print("All required checks passed for this source; every skip or reuse is accounted for.")


if __name__ == "__main__":
    main()
