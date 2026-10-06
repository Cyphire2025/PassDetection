"""Cross-commit CI evidence must retain source, time, scope and success boundaries."""
import copy
import datetime as dt
import subprocess
import unittest
from unittest.mock import Mock

from ci_success_reuse import EvidenceUnavailable, GitHubAPI, discover_reuse

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

    def response(self, path):
        if "/workflows/" in path:
            return {"workflow_runs": self.runs}
        return {"total_count": len(self.jobs), "jobs": self.jobs}

    def discover(self):
        return discover_reuse(self.context, {"backend-test": FINGERPRINT}, NAMES, api=self.api,
                              fingerprint_at=self.fingerprint, ancestor=self.ancestor,
                              tree_at=self.tree, now=NOW)

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
                 "status": "in_progress", "conclusion": "cancelled"}
        for key, value in cases.items():
            with self.subTest(key=key):
                self.runs = [{**self.run, key: value}]
                self.assertEqual(self.discover(), {})

    def test_pr_identity_and_merge_base_are_not_inferred_from_current_ref(self):
        for field, value in (("number", 99), ("base.sha", HEAD), ("base.ref", "develop"),
                             ("base.repo.id", 23), ("head.repo.id", 23),
                             ("head.sha", HEAD), ("head.ref", "codex/other")):
            with self.subTest(field=field):
                changed = copy.deepcopy(self.run)
                target = changed["pull_requests"][0]
                pieces = field.split(".")
                for piece in pieces[:-1]:
                    target = target[piece]
                target[pieces[-1]] = value
                self.runs = [changed]
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


if __name__ == "__main__":
    unittest.main()
