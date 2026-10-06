"""Reuse recent, authoritative successful automatic checks for identical Git inputs.

This returns evidence, never deployable artifacts or cached test outcomes. Manual
Full releases do not use it. Missing Git/API evidence means run the check afresh.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import zipfile

SHA = re.compile(r"[0-9a-f]{40}")
FINGERPRINT = re.compile(r"[0-9a-f]{64}")
MAX_AGE = dt.timedelta(hours=24)
RUN_CONCLUSIONS = frozenset({
    "success", "failure", "cancelled", "timed_out", "action_required",
    "stale", "neutral", "startup_failure",
})


class EvidenceUnavailable(ValueError):
    """A bounded, secret-free failure to read authoritative GitHub evidence."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        raise EvidenceUnavailable("GitHub evidence redirect refused")


class _ArtifactRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        destination = urllib.parse.urlsplit(new_url)
        if destination.scheme != "https" or destination.username or destination.password or destination.port not in {None, 443}:
            raise EvidenceUnavailable("Unsafe artifact redirect refused")
        result = super().redirect_request(request, response, code, message, headers, new_url)
        if result is not None and destination.hostname != "api.github.com":
            result.remove_header("Authorization")
        return result


class GitHubAPI:
    def __init__(self, repository: str, token: str | None = None):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise EvidenceUnavailable("Invalid evidence repository")
        self.prefix = f"/repos/{repository}/actions/"
        self.token = token if token is not None else os.environ.get("GH_TOKEN", "")
        self.opener = urllib.request.build_opener(_NoRedirect())

    def __call__(self, path: str) -> dict:
        if not path.startswith(self.prefix) or "#" in path or "\\" in path:
            raise EvidenceUnavailable("Evidence endpoint is outside the workflow repository")
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
                   "User-Agent": "PassDetection-CI-evidence"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        try:
            request = urllib.request.Request("https://api.github.com" + path, headers=headers)
            with self.opener.open(request, timeout=15) as response:
                payload = response.read(5_000_001)
            if len(payload) > 5_000_000:
                raise EvidenceUnavailable("Evidence response exceeded its bound")
            document = json.loads(payload)
            if not isinstance(document, dict):
                raise EvidenceUnavailable("Evidence response is not an object")
            return document
        except (OSError, ValueError, urllib.error.URLError):
            raise EvidenceUnavailable("GitHub evidence unavailable; run checks afresh") from None

    def download_artifact(self, artifact_id: int) -> bytes:
        if not _positive_id(artifact_id):
            raise EvidenceUnavailable("Invalid artifact identity")
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "PassDetection-CI-evidence"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(
            f"https://api.github.com{self.prefix}artifacts/{artifact_id}/zip", headers=headers)
        try:
            with urllib.request.build_opener(_ArtifactRedirect()).open(request, timeout=15) as response:
                payload = response.read(1_000_001)
            if len(payload) > 1_000_000:
                raise EvidenceUnavailable("Provenance archive exceeded its bound")
            return payload
        except (OSError, ValueError, urllib.error.URLError):
            raise EvidenceUnavailable("GitHub artifact unavailable; run checks afresh") from None


def _positive_id(value) -> bool:
    return type(value) is int and value > 0


def _date(value):
    try:
        result = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result.astimezone(dt.timezone.utc) if result.tzinfo else None
    except (AttributeError, TypeError, ValueError):
        return None


def _fresh(value, now):
    stamp = _date(value)
    return stamp if stamp is not None and dt.timedelta(0) <= now - stamp <= MAX_AGE else None


def _same_run_scope(run, context, now):
    return (isinstance(run, dict) and _positive_id(run.get("id"))
            and run["id"] != context["run_id"]
            and run.get("workflow_id") == context["workflow_id"]
            and run.get("path") == context["workflow_path"]
            and run.get("event") == context["event"]
            and run.get("head_branch") == context["head_branch"]
            and run.get("repository", {}).get("id") == context["repository_id"]
            and run.get("repository", {}).get("full_name") == context["repository"]
            and run.get("head_repository", {}).get("id") == context["repository_id"]
            and isinstance(run.get("head_sha"), str) and SHA.fullmatch(run["head_sha"])
            and _positive_id(run.get("run_attempt"))
            and run.get("status") == "completed"
            and _fresh(run.get("created_at"), now) is not None)


def load_provenance(run, jobs, context, *, api):
    """Read an immutable planner artifact; mutable PR associations are not history.

    Its upload must be wholly within the successful planner job. Every producer
    job depends on that completed planner, so later test code cannot impersonate
    the artifact's producer by uploading another receipt with the same name.
    """
    planners = [job for job in jobs if job.get("name") == "Plan affected checks"]
    if len(planners) != 1:
        return None
    planner = planners[0]
    started, completed = _date(planner.get("started_at")), _date(planner.get("completed_at"))
    if (planner.get("status") != "completed" or planner.get("conclusion") != "success"
            or planner.get("run_id") != run["id"] or planner.get("run_attempt") != run["run_attempt"]
            or planner.get("head_sha") != run["head_sha"] or started is None or completed is None or started > completed):
        return None
    document = api(f"/repos/{context['repository']}/actions/runs/{run['id']}/artifacts?per_page=100")
    rows = document.get("artifacts")
    if (not isinstance(rows, list) or type(document.get("total_count")) is not int
            or document["total_count"] != len(rows) or len(rows) > 100):
        return None
    name = f"ci-provenance-{run['id']}-{run['run_attempt']}"
    matches = [row for row in rows if isinstance(row, dict) and row.get("name") == name]
    if len(matches) != 1:
        return None
    artifact = matches[0]
    created, updated = _date(artifact.get("created_at")), _date(artifact.get("updated_at"))
    binding = artifact.get("workflow_run", {})
    if (artifact.get("expired") is not False or not _positive_id(artifact.get("id"))
            # REST timestamps are rounded to seconds. Exclude the completion
            # second, when a dependent producer may already have started.
            or created is None or updated is None or not started <= created <= updated < completed
            or binding.get("id") != run["id"] or binding.get("head_sha") != run["head_sha"]
            or binding.get("repository_id") != context["repository_id"]
            or binding.get("head_repository_id") != context["repository_id"]
            or binding.get("head_branch") != context["head_branch"]
            or not isinstance(artifact.get("digest"), str)
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", artifact["digest"])):
        return None
    payload = api.download_artifact(artifact["id"])
    if (not isinstance(payload, bytes) or len(payload) > 1_000_000
            or "sha256:" + hashlib.sha256(payload).hexdigest() != artifact["digest"]):
        return None
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            files = archive.infolist()
            if len(files) != 1 or files[0].filename != "ci-provenance.json" or not 0 < files[0].file_size <= 65_536:
                return None
            receipt = json.loads(archive.read(files[0]))
    except (OSError, ValueError, zipfile.BadZipFile, RuntimeError):
        return None
    expected = {"schema_version": 1, "run_id": run["id"], "run_attempt": run["run_attempt"],
                "repository": context["repository"], "repository_id": context["repository_id"],
                "workflow_id": context["workflow_id"], "event": context["event"],
                "head_branch": context["head_branch"], "head_sha": run["head_sha"]}
    if (not isinstance(receipt, dict) or any(receipt.get(key) != value for key, value in expected.items())
            or any(not isinstance(receipt.get(key), str) or not SHA.fullmatch(receipt[key])
                   for key in ("source_sha", "tree_sha"))):
        return None
    if context["event"] == "pull_request":
        if receipt.get("pull_request") != context["pull_request"]:
            return None
        associations = run.get("pull_requests")
        if (not isinstance(associations, list) or len(associations) != 1
                or associations[0].get("number") != receipt["pull_request"]["number"]):
            return None
    elif receipt["source_sha"] != run["head_sha"]:
        return None
    return receipt


def discover_reuse(context, fingerprints, job_names, *, api, fingerprint_at, ancestor, tree_at,
                   now=None, provenance_loader=load_provenance):
    """Return job-id keyed proof for eligible checks; adapters never execute prior code.

    ``fingerprint_at(revision, job_id)`` hashes reviewed Git inputs; ``ancestor``
    and ``tree_at`` inspect locally available objects. Unavailable objects are
    refused, never fetched from API-supplied URLs. PR reuse requires an unchanged
    base already contained in both heads, making its tested merge tree unambiguous.
    A newer matching-input failure overrides an older success; skipped jobs cannot
    become evidence or extend the original successful check's expiry.
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    try:
        if (context["event"] not in {"push", "pull_request"} or not now.tzinfo
                or any(not _positive_id(context[key]) for key in ("repository_id", "workflow_id", "run_id"))
                or any(not isinstance(context[key], str) or not SHA.fullmatch(context[key])
                       for key in ("source_sha", "head_sha"))
                or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", context["repository"])
                or context["workflow_path"] != ".github/workflows/ci.yml"
                or not isinstance(context["head_branch"], str) or not context["head_branch"]
                or not fingerprints or set(fingerprints) - set(job_names)
                or len(set(job_names.values())) != len(job_names)
                or any(not isinstance(value, str) or not FINGERPRINT.fullmatch(value)
                       for value in fingerprints.values())):
            return {}
        if context["event"] == "pull_request":
            pr = context["pull_request"]
            if (not _positive_id(pr["number"]) or pr["head_repo_id"] != context["repository_id"]
                    or pr["head_ref"] != context["head_branch"]
                    or not isinstance(pr["base_sha"], str) or not SHA.fullmatch(pr["base_sha"])
                    or not isinstance(pr["base_ref"], str) or not pr["base_ref"]
                    or not ancestor(pr["base_sha"], context["head_sha"])):
                return {}
        elif context["source_sha"] != context["head_sha"]:
            return {}
        source_tree, head_tree = tree_at(context["source_sha"]), tree_at(context["head_sha"])
        if (not isinstance(source_tree, str) or not SHA.fullmatch(source_tree)
                or source_tree != head_tree):
            return {}
        # Independently bind every caller-supplied fingerprint to this checkout.
        if any(fingerprint_at(context["source_sha"], job) != value for job, value in fingerprints.items()):
            return {}
        prefix = f"/repos/{context['repository']}/actions"
        query = urllib.parse.urlencode({"branch": context["head_branch"], "event": context["event"],
                                       "status": "completed", "per_page": 20})
        document = api(f"{prefix}/workflows/{context['workflow_id']}/runs?{query}")
        runs = document.get("workflow_runs")
        if not isinstance(runs, list) or len(runs) > 20:
            return {}
        latest = {}
        for run in runs:
            if not _same_run_scope(run, context, now):
                continue
            revision = run["head_sha"]
            try:
                if context["event"] == "pull_request":
                    if not ancestor(pr["base_sha"], revision):
                        continue
                elif not ancestor(revision, context["head_sha"]):
                    continue
                matching = {job for job, value in fingerprints.items() if fingerprint_at(revision, job) == value}
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
                continue
            if not matching:
                continue
            document = api(f"{prefix}/runs/{run['id']}/attempts/{run['run_attempt']}/jobs?per_page=100")
            jobs = document.get("jobs")
            if (not isinstance(jobs, list) or type(document.get("total_count")) is not int
                    or document["total_count"] != len(jobs) or len(jobs) > 100):
                return {}
            receipt = provenance_loader(run, jobs, context, api=api)
            if receipt is None:
                return {}
            try:
                if tree_at(revision) != receipt["tree_sha"]:
                    return {}
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
                return {}
            # The overall run may be cancelled after one real check failed.
            # Inspect its authoritative jobs too, so it cannot expose an older
            # success by disappearing from consideration. Unknown conclusions
            # cannot safely authorize falling back to older matching evidence.
            if run.get("conclusion") not in RUN_CONCLUSIONS:
                return {}
            for identifier in matching:
                observations = [job for job in jobs if isinstance(job, dict) and job.get("name") == job_names[identifier]]
                if len(observations) != 1:
                    continue
                job = observations[0]
                stamp = _fresh(job.get("completed_at"), now)
                if (job.get("status") != "completed" or job.get("conclusion") == "skipped" or stamp is None
                        or stamp < _date(run["created_at"])
                        or not _positive_id(job.get("id")) or job.get("run_id") != run["id"]
                        or job.get("run_attempt") != run["run_attempt"] or job.get("head_sha") != revision):
                    continue
                if identifier in latest and (latest[identifier][0] > stamp
                        or (latest[identifier][0] == stamp and latest[identifier][1] is None)):
                    continue
                evidence = {"run_id": run["id"], "job_id": job["id"], "completed_at": job["completed_at"],
                            "source_revision": receipt["source_sha"], "fingerprint": fingerprints[identifier],
                            "url": f"https://github.com/{context['repository']}/actions/runs/{run['id']}/job/{job['id']}"}
                latest[identifier] = (stamp, evidence if job.get("conclusion") == "success" else None)
        return {job: row[1] for job, row in latest.items() if row[1] is not None}
    except (KeyError, TypeError, AttributeError, OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        return {}
