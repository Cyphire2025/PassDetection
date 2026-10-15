"""Authorization and qualification gates for the restricted deployment key."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml

import release_ci_dispatch as dispatch
from release_ci_dispatch import REPOSITORY, REQUIRED_JOBS, qualified_run, requested_revision

SHA = "a" * 40


class DispatchTests(unittest.TestCase):
    def test_required_gate_names_match_the_checked_in_workflow_exactly(self):
        path = Path(__file__).resolve().parents[1] / '.github/workflows/ci.yml'
        workflow = yaml.safe_load(path.read_text(encoding='utf-8'))
        names = {job.get('name', identifier) for identifier, job in workflow['jobs'].items()}
        self.assertEqual(REQUIRED_JOBS - names, set())

    @unittest.skipUnless(os.name == "posix", "The VPS uses Linux flock")
    def test_surviving_deployment_excludes_another_dispatch_and_releases_lock(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(dispatch, "ROOT", Path(directory)):
            with dispatch.dispatch_lock():
                with self.assertRaisesRegex(ValueError, "Another CI deployment"):
                    with dispatch.dispatch_lock():
                        self.fail("Two dispatchers entered the critical section")
            with dispatch.dispatch_lock():
                pass

    def test_superseded_main_is_refused_after_refresh(self):
        with patch.object(dispatch, "run", side_effect=["", "b" * 40]) as command:
            with self.assertRaisesRegex(ValueError, "superseded release"):
                dispatch.require_current_main(SHA)
            self.assertEqual(command.call_args_list[0].args, ("git", "fetch", "origin", "main"))

    def test_key_accepts_only_exact_revision_command(self):
        self.assertEqual(requested_revision("deploy-qualified:" + SHA), SHA)
        for value in ("", "bash", "deploy-qualified:main", "deploy-qualified:" + SHA + "\n",
                      "deploy-qualified:" + SHA + "; id", "deploy-qualified:" + "A" * 40):
            with self.subTest(value=value), self.assertRaises(ValueError):
                requested_revision(value)

    def test_requires_every_successful_gate_for_exact_main_push(self):
        good = {"id": 7, "head_sha": SHA, "head_branch": "main", "event": "push",
                "path": ".github/workflows/ci.yml", "repository": {"full_name": REPOSITORY}}
        jobs = [{"name": name, "conclusion": "success"} for name in REQUIRED_JOBS]
        self.assertEqual(qualified_run([good], SHA, lambda _: jobs), 7)
        self.assertEqual(qualified_run([{**good, "event": "workflow_dispatch"}], SHA, lambda _: jobs), 7)
        for field, value in (("head_sha", "b" * 40), ("head_branch", "develop"),
                             ("event", "pull_request"), ("path", ".github/workflows/other.yml"),
                             ("repository", {"full_name": "untrusted/fork"})):
            with self.subTest(field=field), self.assertRaises(ValueError):
                qualified_run([{**good, field: value}], SHA, lambda _: jobs)
        for name in REQUIRED_JOBS:
            for status in ("failure", "skipped", "cancelled", None):
                changed = [dict(job, conclusion=status) if job["name"] == name else job for job in jobs]
                with self.subTest(job=name, status=status), self.assertRaises(ValueError):
                    qualified_run([good], SHA, lambda _: changed)
            with self.subTest(missing=name), self.assertRaises(ValueError):
                qualified_run([good], SHA, lambda _: [job for job in jobs if job["name"] != name])


if __name__ == "__main__":
    unittest.main()
