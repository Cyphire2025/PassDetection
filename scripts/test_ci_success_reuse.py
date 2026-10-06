"""Cross-commit CI evidence must retain source, time, scope and success boundaries."""
import datetime as dt
import hashlib
import io
import json
import subprocess
import unittest
import urllib.request
import zipfile
from unittest.mock import Mock

from ci_success_reuse import (
    EvidenceUnavailable,
    GitHubAPI,
    _ArtifactRedirect,
    discover_reuse,
    load_provenance,
)

NOW = dt.datetime(2026, 10, 7, 1, tzinfo=dt.timezone.utc)
HEAD, PRIOR, BASE, MERGE = (letter * 40 for letter in "abcd")
FINGERPRINT = "e" * 64
NAMES = {"backend-test": "Backend — Tests"}


class ReuseTests(unittest.TestCase):
    def setUp(self):
        self.context = {"repository": "Cyphire2025/PassDetection", "repository_id": 22,
                        "workflow_id": 33, "workflow_path": ".github/workflows/ci.yml",
                        "event": "pull_request", "head_branch": "codex/fix", "head_sha": HEAD,
                        "source_sha": MERGE, "run_id": 200,
                        "pull_request": {"number": 15, "base_sha": BASE, "base_ref": "main",
                                         "head_ref": "codex/fix", "head_repo_id": 22}}
        self.run = {"id": 100, "workflow_id": 33, "path": ".github/workflows/ci.yml",
                    "event": "pull_request", "head_branch": "codex/fix", "head_sha": PRIOR,
                    "run_attempt": 1, "status": "completed", "conclusion": "failure",
                    "created_at": "2026-10-07T00:00:00Z",
                    "repository": {"id": 22, "full_name": "Cyphire2025/PassDetection"},
                    "head_repository": {"id": 22},
                    "pull_requests": [{"number": 15, "head": {"sha": PRIOR, "ref": "codex/fix", "repo": {"id": 22}},
                                       "base": {"sha": BASE, "ref": "main", "repo": {"id": 22}}}]}
        self.job = {"id": 110, "run_id": 100, "run_attempt": 1, "head_sha": PRIOR,
                    "name": NAMES["backend-test"], "status": "completed", "conclusion": "success",
                    "completed_at": "2026-10-07T00:30:00Z"}
        self.runs = [self.run]
        self.jobs = [self.job]
        self.api = Mock(side_effect=self.response)
        self.fingerprint = Mock(return_value=FINGERPRINT)
        self.ancestor = Mock(return_value=True)
        self.tree = Mock(return_value="f" * 40)
        self.provenance = Mock(return_value={"tree_sha": "f" * 40, "source_sha": PRIOR})

    def response(self, path):
        if "/workflows/" in path:
            return {"workflow_runs": self.runs}
        return {"total_count": len(self.jobs), "jobs": self.jobs}

    def discover(self):
        return discover_reuse(self.context, {"backend-test": FINGERPRINT}, NAMES, api=self.api,
                              fingerprint_at=self.fingerprint, ancestor=self.ancestor,
                              tree_at=self.tree, now=NOW, provenance_loader=self.provenance)

    def test_actual_success_survives_an_unrelated_failed_job_in_the_run(self):
        proof = self.discover()["backend-test"]
        self.assertEqual(proof, {"run_id": 100, "job_id": 110, "source_revision": PRIOR,
                               "completed_at": self.job["completed_at"], "fingerprint": FINGERPRINT,
                               "url": "https://github.com/Cyphire2025/PassDetection/actions/runs/100/job/110"})
        self.fingerprint.assert_any_call(MERGE, "backend-test")
        self.fingerprint.assert_any_call(PRIOR, "backend-test")
        self.assertIn("/attempts/1/jobs?per_page=100", self.api.call_args.args[0])

    def test_unauthoritative_or_different_scope_is_never_reused(self):
        cases = {"id": 200, "workflow_id": 44, "path": ".github/workflows/fake.yml",
                 "event": "push", "head_branch": "main", "head_sha": "main",
                 "repository": {"id": 23, "full_name": "Cyphire2025/PassDetection"},
                 "head_repository": {"id": 23}, "run_attempt": 0,
                 "status": "in_progress", "conclusion": "unknown"}
        for key, value in cases.items():
            with self.subTest(key=key):
                self.runs = [{**self.run, key: value}]
                self.assertEqual(self.discover(), {})

    def test_unavailable_immutable_provenance_requires_fresh_execution(self):
        self.provenance.return_value = None
        self.assertEqual(self.discover(), {})

    def test_missing_newer_provenance_cannot_expose_an_older_success(self):
        other = {**self.run, "id": 101}
        self.runs = [self.run, other]
        self.provenance.side_effect = [{"tree_sha": "f" * 40, "source_sha": PRIOR}, None]
        self.assertEqual(self.discover(), {})

    def test_tested_merge_tree_must_equal_prior_head_tree_before_hashing_head(self):
        self.provenance.return_value = {"tree_sha": "e" * 40, "source_sha": MERGE}
        self.assertEqual(self.discover(), {})

    def test_unavailable_or_divergent_git_tree_runs_checks_afresh(self):
        self.tree.side_effect = ["merge", "head"]
        self.assertEqual(self.discover(), {})
        self.api.assert_not_called()
        self.tree.side_effect = None
        self.ancestor.return_value = False
        self.assertEqual(self.discover(), {})
        self.ancestor.return_value = True
        self.fingerprint.side_effect = [FINGERPRINT, subprocess.CalledProcessError(128, "git")]
        self.assertEqual(self.discover(), {})

    def test_missing_current_tree_cannot_compare_equal_and_authorize_reuse(self):
        self.tree.return_value = None
        self.assertEqual(self.discover(), {})
        self.api.assert_not_called()

    def test_job_cannot_finish_before_its_source_run_exists(self):
        self.job["completed_at"] = "2026-10-06T23:59:59Z"
        self.assertEqual(self.discover(), {})

    def test_input_change_or_unbound_current_fingerprint_runs_afresh(self):
        self.fingerprint.side_effect = [FINGERPRINT, "f" * 64]
        self.assertEqual(self.discover(), {})
        self.api.reset_mock()
        self.fingerprint.side_effect = ["f" * 64]
        self.assertEqual(self.discover(), {})
        self.api.assert_not_called()

    def test_missing_duplicate_skipped_failed_or_incomplete_jobs_are_not_proof(self):
        for value in ([], [self.job, self.job], [{**self.job, "conclusion": "failure"}],
                      [{**self.job, "conclusion": "skipped"}], [{**self.job, "conclusion": "cancelled"}],
                      [{**self.job, "status": "in_progress"}], [{**self.job, "head_sha": HEAD}],
                      [{**self.job, "run_attempt": 2}], [{**self.job, "run_id": 101}]):
            with self.subTest(value=value):
                self.jobs = value
                self.assertEqual(self.discover(), {})

    def test_expired_future_or_naive_evidence_is_rejected(self):
        for stamp in ("2026-10-05T23:00:00Z", "2026-10-07T02:00:00Z", "2026-10-07T00:00:00", "bad", None):
            with self.subTest(stamp=stamp):
                self.jobs = [{**self.job, "completed_at": stamp}]
                self.assertEqual(self.discover(), {})
                self.jobs = [self.job]
                self.runs = [{**self.run, "created_at": stamp}]
                self.assertEqual(self.discover(), {})
                self.runs = [self.run]

    def test_newer_matching_failure_cannot_be_hidden_by_an_older_pass(self):
        other = {**self.run, "id": 101}
        failure = {**self.job, "id": 111, "run_id": 101, "conclusion": "failure", "completed_at": "2026-10-07T00:40:00Z"}
        for runs in ([other, self.run], [self.run, other]):
            self.runs = runs
            self.api.side_effect = lambda path: ({"workflow_runs": self.runs} if "/workflows/" in path else
                {"total_count": 1, "jobs": [failure if "/101/" in path else self.job]})
            self.assertEqual(self.discover(), {})

    def test_older_ambiguous_receipt_cannot_poison_newer_proven_success(self):
        other = {**self.run, "id": 101}
        old_job = {**self.job, "id": 111, "run_id": 101,
                   "completed_at": "2026-10-07T00:20:00Z"}
        invalid_receipts = (None, {"tree_sha": "e" * 40, "source_sha": PRIOR})
        for invalid in invalid_receipts:
            for result in ("success", "failure", "cancelled"):
                for runs in ([other, self.run], [self.run, other]):
                    with self.subTest(receipt=invalid, result=result, order=[x["id"] for x in runs]):
                        self.runs = runs
                        observation = {**old_job, "conclusion": result}
                        self.api.side_effect = lambda path, observation=observation: (
                            {"workflow_runs": self.runs} if "/workflows/" in path else
                            {"total_count": 1, "jobs": [observation if "/101/" in path else self.job]})
                        self.provenance.side_effect = lambda run, jobs, context, api, invalid=invalid: (
                            invalid if run["id"] == 101 else {"tree_sha": "f" * 40, "source_sha": PRIOR})
                        self.assertEqual(self.discover()["backend-test"]["job_id"], self.job["id"])

    def test_superseded_old_receipt_is_not_downloaded(self):
        other = {**self.run, "id": 101}
        self.runs = [self.run, other]
        old_job = {**self.job, "id": 111, "run_id": 101,
                   "completed_at": "2026-10-07T00:20:00Z"}
        self.api.side_effect = lambda path: ({"workflow_runs": self.runs} if "/workflows/" in path else
            {"total_count": 1, "jobs": [old_job if "/101/" in path else self.job]})
        self.assertIn("backend-test", self.discover())
        self.assertEqual([call.args[0]["id"] for call in self.provenance.call_args_list], [100])

    def test_newer_or_equal_ambiguous_receipt_blocks_older_success_in_any_order(self):
        other = {**self.run, "id": 101}
        for stamp in (self.job["completed_at"], "2026-10-07T00:40:00Z"):
            for invalid in (None, {"tree_sha": "e" * 40, "source_sha": PRIOR}):
                for result in ("success", "failure", "cancelled"):
                    for runs in ([other, self.run], [self.run, other]):
                        with self.subTest(stamp=stamp, receipt=invalid, result=result,
                                          order=[x["id"] for x in runs]):
                            self.runs = runs
                            job = {**self.job, "id": 111, "run_id": 101,
                                   "conclusion": result, "completed_at": stamp}
                            self.api.side_effect = lambda path, job=job: (
                                {"workflow_runs": self.runs} if "/workflows/" in path else
                                {"total_count": 1, "jobs": [job if "/101/" in path else self.job]})
                            self.provenance.side_effect = lambda run, jobs, context, api, invalid=invalid: (
                                invalid if run["id"] == 101 else {"tree_sha": "f" * 40, "source_sha": PRIOR})
                            self.assertEqual(self.discover(), {})

    def test_unorderable_job_metadata_cannot_hide_possible_newer_failure(self):
        other = {**self.run, "id": 101}
        base_job = {**self.job, "id": 111, "run_id": 101, "conclusion": "failure"}
        malformed = [
            {**base_job, "completed_at": None}, {**base_job, "completed_at": "bad"},
            {**base_job, "completed_at": "2026-10-07T02:00:00Z"},
            {**base_job, "head_sha": HEAD}, {**base_job, "run_attempt": 2},
            {**base_job, "status": "in_progress"},
        ]
        for job in malformed:
            for runs in ([other, self.run], [self.run, other]):
                with self.subTest(job=job, order=[x["id"] for x in runs]):
                    self.runs = runs
                    self.api.side_effect = lambda path, job=job: (
                        {"workflow_runs": self.runs} if "/workflows/" in path else
                        {"total_count": 1, "jobs": [job if "/101/" in path else self.job]})
                    self.assertEqual(self.discover(), {})

    def test_missing_receipt_blocks_only_jobs_with_actual_newer_observations(self):
        other = {**self.run, "id": 101}
        frontend = {**self.job, "id": 112, "name": "Frontend - Browser Journeys"}
        newer_backend = {**self.job, "id": 111, "run_id": 101,
                         "completed_at": "2026-10-07T00:40:00Z"}
        names = {**NAMES, "frontend-browser": frontend["name"]}
        for runs in ([other, self.run], [self.run, other]):
            with self.subTest(order=[x["id"] for x in runs]):
                self.runs = runs
                self.api.side_effect = lambda path: ({"workflow_runs": self.runs} if "/workflows/" in path else
                    ({"total_count": 1, "jobs": [newer_backend]} if "/101/" in path else
                     {"total_count": 2, "jobs": [self.job, frontend]}))
                self.provenance.side_effect = lambda run, jobs, context, api: (
                    None if run["id"] == 101 else {"tree_sha": "f" * 40, "source_sha": PRIOR})
                result = discover_reuse(
                    self.context, {job: FINGERPRINT for job in names}, names, api=self.api,
                    fingerprint_at=self.fingerprint, ancestor=self.ancestor, tree_at=self.tree,
                    now=NOW, provenance_loader=self.provenance,
                )
                self.assertEqual(set(result), {"frontend-browser"})
                self.assertEqual(result["frontend-browser"]["job_id"], frontend["id"])

    def test_cancelled_or_other_completed_run_still_exposes_newer_job_failure(self):
        for conclusion in ("cancelled", "timed_out", "action_required", "stale", "neutral", "startup_failure"):
            for result in ("failure", "cancelled"):
                with self.subTest(run_conclusion=conclusion, job_conclusion=result):
                    other = {**self.run, "id": 101, "conclusion": conclusion}
                    failure = {**self.job, "id": 111, "run_id": 101, "conclusion": result,
                               "completed_at": "2026-10-07T00:40:00Z"}
                    self.runs = [other, self.run]
                    self.api.side_effect = lambda path, failure=failure: ({"workflow_runs": self.runs} if "/workflows/" in path else
                        {"total_count": 1, "jobs": [failure if "/101/" in path else self.job]})
                    self.assertEqual(self.discover(), {})

    def test_unknown_completed_run_conclusion_cannot_reveal_an_older_success(self):
        for conclusion in (None, "unexpected"):
            with self.subTest(conclusion=conclusion):
                self.runs = [self.run, {**self.run, "id": 101, "conclusion": conclusion}]
                self.assertEqual(self.discover(), {})

    def test_successful_job_before_unrelated_run_cancellation_remains_actual_evidence(self):
        self.run["conclusion"] = "cancelled"
        self.assertEqual(self.discover()["backend-test"]["job_id"], self.job["id"])

    def test_skipped_reuse_does_not_extend_the_original_success_timestamp(self):
        other = {**self.run, "id": 101}
        skipped = {**self.job, "id": 111, "run_id": 101, "conclusion": "skipped", "completed_at": "2026-10-07T00:40:00Z"}
        self.runs = [other, self.run]
        self.api.side_effect = lambda path: ({"workflow_runs": self.runs} if "/workflows/" in path else
            {"total_count": 1, "jobs": [skipped if "/101/" in path else self.job]})
        self.assertEqual(self.discover()["backend-test"]["completed_at"], self.job["completed_at"])

    def test_api_error_or_truncation_cannot_create_partial_success(self):
        self.api.side_effect = EvidenceUnavailable("unavailable")
        self.assertEqual(self.discover(), {})
        self.api.side_effect = lambda path: ({"workflow_runs": self.runs} if "/workflows/" in path else
                                           {"total_count": 101, "jobs": self.jobs})
        self.assertEqual(self.discover(), {})
        self.api.side_effect = None
        self.api.return_value = {"workflow_runs": [self.run] * 21}
        self.assertEqual(self.discover(), {})

    def test_manual_release_does_not_reuse_even_with_successful_evidence(self):
        self.context["event"] = "workflow_dispatch"
        self.assertEqual(self.discover(), {})
        self.api.assert_not_called()

    def test_push_reuse_requires_same_branch_ancestor_and_exact_checkout(self):
        self.context.update(event="push", source_sha=HEAD)
        self.run.update(event="push")
        self.assertIn("backend-test", self.discover())
        self.ancestor.assert_called_with(PRIOR, HEAD)
        self.ancestor.return_value = False
        self.assertEqual(self.discover(), {})

    def test_rest_client_never_follows_an_unrelated_endpoint(self):
        client = GitHubAPI("Cyphire2025/PassDetection", token="test-secret")
        for endpoint in ("https://evil.test", "/repos/elsewhere/repo/actions/runs", "/repos/Cyphire2025/PassDetection/issues"):
            with self.subTest(endpoint=endpoint), self.assertRaises(EvidenceUnavailable) as caught:
                client(endpoint)
            self.assertNotIn("test-secret", str(caught.exception))

    def test_artifact_redirect_drops_authorization_outside_github_api(self):
        request = urllib.request.Request("https://api.github.com/repos/Cyphire2025/PassDetection/actions/artifacts/77/zip",
                                         headers={"Authorization": "Bearer test-secret"})
        redirect = _ArtifactRedirect()
        external = redirect.redirect_request(request, None, 302, "Found", {}, "https://example.test/signed.zip")
        self.assertIsNone(external.get_header("Authorization"))
        for destination in ("http://example.test/file", "https://user:password@example.test/file", "https://example.test:444/file"):
            with self.subTest(destination=destination), self.assertRaises(EvidenceUnavailable):
                redirect.redirect_request(request, None, 302, "Found", {}, destination)


class ProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.context = {"repository": "Cyphire2025/PassDetection", "repository_id": 22,
                        "workflow_id": 33, "event": "pull_request", "head_branch": "codex/fix",
                        "pull_request": {"number": 15, "base_sha": BASE, "base_ref": "main",
                                         "head_ref": "codex/fix", "head_repo_id": 22}}
        self.run = {"id": 100, "run_attempt": 1, "head_sha": PRIOR, "pull_requests": [{"number": 15}]}
        self.planner = {"id": 99, "run_id": 100, "run_attempt": 1, "head_sha": PRIOR,
                        "name": "Plan affected checks", "status": "completed", "conclusion": "success",
                        "started_at": "2026-10-07T00:00:00Z", "completed_at": "2026-10-07T00:02:00Z"}
        self.receipt = {**self.context, "schema_version": 1, "run_id": 100, "run_attempt": 1,
                        "head_sha": PRIOR, "source_sha": MERGE, "tree_sha": "f" * 40}
        self.artifact = {"id": 77, "name": "ci-provenance-100-1", "expired": False,
                         "created_at": "2026-10-07T00:01:00Z", "updated_at": "2026-10-07T00:01:00Z",
                         "workflow_run": {"id": 100, "repository_id": 22, "head_repository_id": 22,
                                          "head_branch": "codex/fix", "head_sha": PRIOR}}
        self.api = Mock()
        self.api.return_value = {"total_count": 1, "artifacts": [self.artifact]}
        self.package()

    def package(self, *, filename="ci-provenance.json", additional=False):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(filename, json.dumps(self.receipt))
            if additional:
                archive.writestr("extra.json", "{}")
        payload = stream.getvalue()
        self.api.download_artifact.return_value = payload
        self.artifact["digest"] = "sha256:" + hashlib.sha256(payload).hexdigest()

    def load(self):
        return load_provenance(self.run, [self.planner], self.context, api=self.api)

    def test_actual_immutable_receipt_binds_tested_merge_source(self):
        self.assertEqual(self.load()["source_sha"], MERGE)
        self.api.download_artifact.assert_called_once_with(77)

    def test_mutable_pr_association_head_and_base_cannot_overrule_saved_receipt(self):
        self.run["pull_requests"][0].update(head={"sha": HEAD}, base={"sha": HEAD})
        self.assertEqual(self.load()["head_sha"], PRIOR)
        self.receipt["pull_request"] = {**self.context["pull_request"], "base_sha": HEAD}
        self.package()
        self.assertIsNone(self.load())

    def test_later_job_upload_cannot_impersonate_planner_evidence(self):
        for field, value in (("created_at", "2026-10-06T23:59:59Z"),
                             ("updated_at", "2026-10-07T00:02:00Z"),
                             ("updated_at", "2026-10-07T00:02:01Z")):
            with self.subTest(field=field):
                original = self.artifact[field]
                self.artifact[field] = value
                self.assertIsNone(self.load())
                self.artifact[field] = original
        self.api.download_artifact.assert_not_called()

    def test_wrong_run_attempt_repository_or_source_is_not_provenance(self):
        for field, value in (("id", 101), ("repository_id", 23), ("head_repository_id", 23),
                             ("head_branch", "other"), ("head_sha", HEAD)):
            with self.subTest(field=field):
                original = self.artifact["workflow_run"][field]
                self.artifact["workflow_run"][field] = value
                self.assertIsNone(self.load())
                self.artifact["workflow_run"][field] = original
        for field, value in (("run_id", 101), ("run_attempt", 2), ("workflow_id", 34),
                             ("head_sha", HEAD), ("tree_sha", "branch"), ("source_sha", "main")):
            with self.subTest(field=field):
                original = self.receipt[field]
                self.receipt[field] = value
                self.package()
                self.assertIsNone(self.load())
                self.receipt[field] = original

    def test_only_one_successful_planner_and_unique_unexpired_artifact(self):
        self.assertIsNone(load_provenance(self.run, [self.planner, self.planner], self.context, api=self.api))
        self.planner["conclusion"] = "failure"
        self.assertIsNone(self.load())
        self.planner["conclusion"] = "success"
        self.artifact["expired"] = True
        self.assertIsNone(self.load())
        self.artifact["expired"] = False
        self.api.return_value = {"total_count": 2, "artifacts": [self.artifact, self.artifact]}
        self.assertIsNone(self.load())

    def test_digest_mismatch_or_extra_zip_payload_is_rejected(self):
        self.artifact["digest"] = "sha256:" + "0" * 64
        self.assertIsNone(self.load())
        self.package(additional=True)
        self.assertIsNone(self.load())
        self.package(filename="../ci-provenance.json")
        self.assertIsNone(self.load())
        self.receipt["padding"] = "a" * 65_536
        self.package()
        self.assertIsNone(self.load())

    def test_missing_old_planner_artifact_is_fresh_execution(self):
        self.api.return_value = {"total_count": 0, "artifacts": []}
        self.assertIsNone(self.load())
        self.assertIsNone(load_provenance(self.run, [], self.context, api=self.api))

    def test_push_receipt_source_must_be_its_immutable_head(self):
        self.context["event"] = self.receipt["event"] = "push"
        self.package()
        self.assertIsNone(self.load())
        self.receipt["source_sha"] = PRIOR
        self.package()
        self.assertIsNotNone(self.load())


if __name__ == "__main__":
    unittest.main()
