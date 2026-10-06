"""Fail-closed selection, coverage union and release-DAG regressions."""
from __future__ import annotations

import copy
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

import yaml
from ci_pipeline import (
    JOB_NAMES,
    JOBS,
    REUSABLE_JOBS,
    collection_digest,
    decide,
    qualified_push_base,
    run_provenance,
    validate_gate,
    verify_shards,
)

SOURCE = "a" * 40
INPUTS = {job: "b" * 64 for job in JOBS}


def evidence():
    return {"source_revision": "c" * 40, "fingerprint": "b" * 64,
            "run_id": 12, "job_id": 13,
            "completed_at": dt.datetime.now(dt.timezone.utc).isoformat()}


def needs_for(plan):
    return {"plan": {"result": "success", "outputs": {"plan": json.dumps(plan)}},
            **{job: {"result": "success" if value["state"] == "run" else "skipped"}
               for job, value in plan["jobs"].items()}}


class GateTests(unittest.TestCase):
    def test_manual_full_ignores_reuse_and_unchanged_paths(self):
        plan = decide(SOURCE, "workflow_dispatch", [], INPUTS,
                      {job: evidence() for job in REUSABLE_JOBS})
        self.assertEqual({value["state"] for value in plan["jobs"].values()}, {"run"})
        self.assertEqual(validate_gate(needs_for(plan), SOURCE, "workflow_dispatch",
                                       INPUTS, set(JOBS)), plan)

    def test_full_rejects_every_missing_failed_cancelled_and_skipped_gate(self):
        plan = decide(SOURCE, "workflow_dispatch", [], INPUTS, {})
        for job in JOBS:
            for result in ("failure", "cancelled", "skipped", None):
                needs = needs_for(plan)
                needs[job]["result"] = result
                with self.subTest(job=job, result=result), self.assertRaises(ValueError):
                    validate_gate(needs, SOURCE, "workflow_dispatch", INPUTS, set(JOBS))
            needs = needs_for(plan)
            del needs[job]
            with self.assertRaises(ValueError):
                validate_gate(needs, SOURCE, "workflow_dispatch", INPUTS, set(JOBS))

    def test_automatic_reuse_keeps_original_evidence_without_claiming_new_execution(self):
        plan = decide(SOURCE, "pull_request", None, INPUTS,
                      {job: evidence() for job in REUSABLE_JOBS})
        self.assertEqual({job for job, value in plan["jobs"].items() if value["state"] == "reuse"},
                         REUSABLE_JOBS)
        self.assertEqual(validate_gate(needs_for(plan), SOURCE, "pull_request", INPUTS, set(JOBS)), plan)

    def test_reuse_refuses_changed_input_missing_evidence_and_expiry(self):
        plan = decide(SOURCE, "pull_request", None, INPUTS, {"backend-test": evidence()})
        for change in ("fingerprint", "evidence", "expiry", "source", "planner"):
            damaged = copy.deepcopy(plan)
            needs = needs_for(damaged)
            if change == "fingerprint":
                damaged["jobs"]["backend-test"]["fingerprint"] = "d" * 64
            elif change == "evidence":
                del damaged["jobs"]["backend-test"]["evidence"]
            elif change == "expiry":
                damaged["jobs"]["backend-test"]["evidence"]["completed_at"] = "2020-01-01T00:00:00Z"
            elif change == "source":
                damaged["source_revision"] = "e" * 40
            else:
                needs["plan"]["result"] = "failure"
            needs["plan"]["outputs"]["plan"] = json.dumps(damaged)
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_gate(needs, SOURCE, "pull_request", INPUTS, set(JOBS))

    def test_affected_job_cannot_be_hidden_as_unrelated(self):
        plan = decide(SOURCE, "pull_request", ["README.md"], INPUTS, {})
        with self.assertRaisesRegex(ValueError, "affected inputs"):
            validate_gate(needs_for(plan), SOURCE, "pull_request", INPUTS, set(JOBS))
        validate_gate(needs_for(plan), SOURCE, "pull_request", INPUTS, {"backend-static-checks"})

    def test_new_push_cannot_hide_a_failed_or_unqualified_predecessor(self):
        repository = "Cyphire2025/PassDetection"
        run = {"id": 4, "head_sha": SOURCE, "workflow_id": 2,
               "path": ".github/workflows/ci.yml", "event": "push", "head_branch": "main",
               "repository": {"full_name": repository}, "status": "completed",
               "conclusion": "success", "run_attempt": 1,
               "created_at": "2026-10-01T00:00:00Z", "updated_at": "2026-10-01T01:00:00Z"}
        gate = {"id": 40, "run_id": 4, "run_attempt": 1, "head_sha": SOURCE,
                "name": "Required CI checks", "status": "completed", "conclusion": "success",
                "completed_at": "2026-10-01T00:50:00Z"}

        def api(_):
            return {"workflow_runs": [run]} if "/workflows/" in _ else {"total_count": 1, "jobs": [gate]}

        self.assertTrue(qualified_push_base(api, repository, 2, SOURCE, "main"))
        for field, value in (("status", "in_progress"), ("head_branch", "develop"),
                             ("head_sha", "f" * 40), ("event", "pull_request")):
            original = run[field]
            run[field] = value
            self.assertFalse(qualified_push_base(api, repository, 2, SOURCE, "main"))
            run[field] = original
        gate["conclusion"] = "skipped"
        self.assertFalse(qualified_push_base(api, repository, 2, SOURCE, "main"))


class PushBaselineTests(unittest.TestCase):
    def setUp(self):
        self.repository = "Cyphire2025/PassDetection"
        self.run = {"id": 4, "head_sha": SOURCE, "workflow_id": 2,
                    "path": ".github/workflows/ci.yml", "event": "workflow_dispatch", "head_branch": "main",
                    "repository": {"full_name": self.repository}, "status": "completed",
                    "conclusion": "success", "run_attempt": 1,
                    "created_at": "2026-10-01T00:00:00Z", "updated_at": "2026-10-01T01:00:00Z"}
        self.gate = {"id": 40, "run_id": 4, "run_attempt": 1, "head_sha": SOURCE,
                     "name": "Required CI checks", "status": "completed", "conclusion": "success",
                     "completed_at": "2026-10-01T00:50:00Z"}
        self.runs, self.jobs = [self.run], {4: [self.gate]}
        self.paths = []

    def api(self, path):
        self.paths.append(path)
        if "/workflows/" in path:
            return {"workflow_runs": self.runs}
        identifier = int(path.split("/runs/")[1].split("/")[0])
        return {"total_count": len(self.jobs[identifier]), "jobs": self.jobs[identifier]}

    def qualified(self):
        return qualified_push_base(self.api, self.repository, 2, SOURCE, "main")

    def other(self, *, updated="2026-10-01T00:55:00Z", gates=True, conclusion="failure"):
        run = {**self.run, "id": 5, "event": "push", "conclusion": conclusion, "updated_at": updated}
        job = {**self.gate, "id": 50, "run_id": 5, "conclusion": conclusion, "completed_at": updated}
        self.runs.append(run)
        self.jobs[5] = [job] if gates else []
        return run, job

    def test_successful_manual_full_or_check_only_release_is_valid_baseline(self):
        self.assertTrue(self.qualified())
        self.assertNotIn("event=push", self.paths[0])
        self.assertNotIn("status=success", self.paths[0])
        self.assertIn("status=completed", self.paths[0])

    def test_newer_failed_or_cancelled_gate_cannot_hide_behind_old_success(self):
        for conclusion in ("failure", "cancelled", "skipped", "timed_out"):
            with self.subTest(conclusion=conclusion):
                self.runs = [self.run]
                self.other(conclusion=conclusion)
                self.assertFalse(self.qualified())
                self.runs.reverse()
                self.assertFalse(self.qualified())

    def test_early_cancelled_duplicate_push_is_superseded_by_later_full_gate(self):
        self.other(updated="2026-10-01T00:20:00Z", gates=False, conclusion="cancelled")
        self.assertTrue(self.qualified())

    def test_later_missing_incomplete_or_ambiguous_gate_requires_fresh_checks(self):
        _, job = self.other(gates=False, conclusion="cancelled")
        self.assertFalse(self.qualified())
        self.jobs[5] = [{**job, "status": "in_progress", "completed_at": None}]
        self.assertFalse(self.qualified())
        self.jobs[5] = [job, job]
        self.assertFalse(self.qualified())

    def test_later_successful_full_resolves_an_earlier_failed_push(self):
        self.other(updated="2026-10-01T00:20:00Z")
        self.assertTrue(self.qualified())
        self.runs.reverse()
        self.assertTrue(self.qualified())

    def test_gate_identity_and_attempt_are_bound_to_its_run(self):
        for key, value in (("run_id", 99), ("run_attempt", 2), ("head_sha", "f" * 40), ("id", True)):
            with self.subTest(key=key):
                self.jobs[4] = [{**self.gate, key: value}]
                self.assertFalse(self.qualified())

    def test_later_deployment_status_cannot_reorder_actual_qualification(self):
        self.run["conclusion"] = "failure"  # CI passed; a later publication step failed.
        self.assertTrue(self.qualified())
        self.other(updated="2026-10-01T00:55:00Z")
        self.run["updated_at"] = "2026-10-01T02:00:00Z"
        self.assertFalse(self.qualified())

    def test_equal_time_negative_gate_wins_and_unknown_dates_are_refused(self):
        other, _ = self.other(updated=self.gate["completed_at"])
        self.assertFalse(self.qualified())
        other["updated_at"] = None
        self.assertFalse(self.qualified())


class ProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.context = {"repository": "Cyphire2025/PassDetection", "repository_id": 10,
                        "workflow_id": 20, "workflow_path": ".github/workflows/ci.yml",
                        "event": "pull_request", "head_branch": "codex/repair",
                        "head_sha": "b" * 40, "source_sha": SOURCE,
                        "run_id": 30, "run_attempt": 1,
                        "pull_request": {"number": 15, "base_sha": "c" * 40,
                                         "base_ref": "main", "head_ref": "codex/repair",
                                         "head_repo_id": 10}}
        self.run = {"id": 30, "run_attempt": 1, "event": "pull_request",
                    "path": ".github/workflows/ci.yml",
                    "repository": {"id": 10, "full_name": "Cyphire2025/PassDetection"}}
        self.payload = {"pull_request": {"head": {"sha": "b" * 40}}}

    def test_records_tested_checkout_and_original_event_not_mutable_pr_association(self):
        self.run["pull_requests"] = [{"head": {"sha": "f" * 40}}]
        receipt = run_provenance(self.context, self.run, self.payload, "d" * 40)
        self.assertEqual(receipt["source_sha"], SOURCE)
        self.assertEqual(receipt["head_sha"], "b" * 40)
        self.assertEqual(receipt["tree_sha"], "d" * 40)
        self.assertEqual(receipt["pull_request"]["base_sha"], "c" * 40)
        self.assertNotIn("workflow_path", receipt)

    def test_refuses_other_run_attempt_event_or_repository(self):
        for key, value in (("id", 31), ("run_attempt", 2), ("event", "workflow_dispatch"),
                           ("repository", {"id": 11, "full_name": "someone/fork"}),
                           ("path", ".github/workflows/untrusted.yml")):
            run = {**self.run, key: value}
            with self.subTest(key=key), self.assertRaises(ValueError):
                run_provenance(self.context, run, self.payload, "d" * 40)

    def test_refuses_mismatched_event_head_or_push_checkout(self):
        self.payload["pull_request"]["head"]["sha"] = "e" * 40
        with self.assertRaises(ValueError):
            run_provenance(self.context, self.run, self.payload, "d" * 40)
        self.context["event"] = self.run["event"] = "push"
        del self.context["pull_request"]
        with self.assertRaises(ValueError):
            run_provenance(self.context, self.run, {}, "d" * 40)
        self.context["source_sha"] = self.context["head_sha"]
        self.assertEqual(run_provenance(self.context, self.run, {}, "d" * 40)["event"], "push")


class ShardUnionTests(unittest.TestCase):
    def receipts(self, directory):
        nodeids = [f"tests/test_sample.py::test_case[{index}]" for index in range(12)]
        for index in range(1, 5):
            report = {"schema_version": 1, "shard_index": index, "shard_count": 4,
                      "collection_count": len(nodeids), "collection_sha256": collection_digest(nodeids),
                      "selected_nodeids": nodeids[index - 1::4]}
            (directory / f"ci-shard-{index}.json").write_text(json.dumps(report), encoding="utf-8")
            (directory / f".coverage.shard-{index}").write_bytes(b"coverage-test-placeholder")

    def test_union_includes_every_collected_item_exactly_once(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            self.receipts(directory)
            verify_shards(directory, 4)

    def test_rejects_missing_duplicate_mismatched_or_uncovered_shards(self):
        for damage in ("missing", "duplicate", "omitted", "coverage", "empty_coverage",
                       "hash", "count", "index", "schema"):
            with self.subTest(damage=damage), tempfile.TemporaryDirectory() as folder:
                directory = Path(folder)
                self.receipts(directory)
                path = directory / "ci-shard-2.json"
                report = json.loads(path.read_text())
                if damage == "missing":
                    path.unlink()
                elif damage in {"coverage", "empty_coverage"}:
                    coverage = directory / ".coverage.shard-2"
                    if damage == "coverage":
                        coverage.unlink()
                    else:
                        coverage.write_bytes(b"")
                else:
                    if damage == "duplicate":
                        report["selected_nodeids"][0] = "tests/test_sample.py::test_case[0]"
                    elif damage == "omitted":
                        report["selected_nodeids"].pop()
                    elif damage == "hash":
                        report["collection_sha256"] = "f" * 64
                    elif damage == "count":
                        report["collection_count"] += 1
                    elif damage == "index":
                        report["shard_index"] = 1
                    else:
                        report["schema_version"] = 2
                    path.write_text(json.dumps(report), encoding="utf-8")
                with self.assertRaises(ValueError):
                    verify_shards(directory, 4)


class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = yaml.safe_load((Path(__file__).resolve().parents[1] / ".github/workflows/ci.yml").read_text("utf-8"))

    def test_parallel_work_has_one_small_prerequisite_and_full_has_required_gate(self):
        jobs = self.workflow["jobs"]
        self.assertEqual(jobs["docker-build"]["needs"], "plan")
        self.assertEqual(jobs["backend-test-shards"]["needs"], "plan")
        self.assertEqual(jobs["backend-test-shards"]["strategy"]["matrix"]["shard"], [1, 2, 3, 4])
        self.assertIs(jobs["backend-test-shards"]["strategy"]["fail-fast"], False)
        self.assertEqual(set(jobs["required-checks"]["needs"]), {"plan", *JOBS})
        self.assertIn("always()", jobs["required-checks"]["if"])
        self.assertEqual(set(jobs["publish-qualified-artifacts"]["needs"]),
                         {"required-checks", "docker-build", "connector-windows"})
        for job in JOBS:
            self.assertEqual(jobs[job]["name"], JOB_NAMES[job])

    def test_security_failure_is_early_and_signed_archives_only_follow_manual_full(self):
        steps = self.workflow["jobs"]["docker-build"]["steps"]
        names = [step.get("name", "") for step in steps]
        install = next(index for index, step in enumerate(steps)
                       if "pip install --require-hashes -r backend/requirements-dev.lock" in step.get("run", ""))
        self.assertLess(install, names.index("Enforce backend whole-image vulnerability policy"))
        self.assertLess(names.index("Enforce backend whole-image vulnerability policy"),
                        names.index("Prepare isolated production-image stack"))
        for name in ("Export the exact qualified images without rebuilding",
                     "Sign qualified archive and full-image SBOM checksums",
                     "Retain exact qualified image archives for promotion"):
            condition = steps[names.index(name)]["if"]
            self.assertIn("github.event_name == 'workflow_dispatch'", condition)
            self.assertIn("inputs.deployment_mode == 'full'", condition)
            self.assertIn("github.ref == 'refs/heads/main'", condition)


if __name__ == "__main__":
    unittest.main()
