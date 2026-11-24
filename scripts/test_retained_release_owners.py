"""Shared retained release ownership controls with no operational credentials."""

import os
import pickle
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import get_type_hints

import release_document_resources as resources
import release_retained_update as facade
from test_release_retained_update import SHA, live_rows, select_live


class ProbeUpdate(facade.RetainedUpdate):
    def candidate_environment(self, original: dict) -> dict[str, str]:
        result = super().candidate_environment(original)
        return {**result, "SYNTHETIC_OVERRIDE": "retained"}

    def fast_images(self) -> dict:
        self.events.append("before-super")
        result = super().fast_images()
        self.events.append("after-super")
        return result


class RetainedOwnerTests(unittest.TestCase):
    def test_public_aliases_hints_and_static_only_state_are_preserved(self):
        self.assertEqual(get_type_hints(facade.RetainedUpdate), {})
        self.assertEqual(
            [cls.__name__ for cls in facade.RetainedUpdate.__mro__[1:-1]],
            ["_RetainedBuild", "_RetainedRuntime", "_RetainedHost"],
        )
        for cls in facade.RetainedUpdate.__mro__[1:-1]:
            self.assertEqual(get_type_hints(cls), {})
            for name in ("__init__", "__slots__", "__getattr__", "root", "record"):
                self.assertNotIn(name, vars(cls))
        for value in (facade.RetainedUpdate, facade.FastBuild, facade.select_live):
            self.assertIs(pickle.loads(pickle.dumps(value)), value)
        self.assertEqual(get_type_hints(facade.RetainedUpdate.schema), {"return": str})

    def test_actual_subclass_super_and_environment_override_dispatch(self):
        release = object.__new__(ProbeUpdate)
        release.revision = SHA
        release.pause_email_and_photos = False
        original = select_live(live_rows())["backend"]
        result = release.candidate_environment(original)
        self.assertEqual(result["APP_REVISION"], SHA)
        self.assertEqual(result["EXPECTED_DATABASE_SCHEMA_REVISION"], facade.SCHEMA)
        self.assertEqual(result["SYNTHETIC_OVERRIDE"], "retained")
        self.assertEqual(result["PRIVATE_SETTING"], "retained")

    def test_super_fast_images_drains_and_resumes_before_returning(self):
        release = object.__new__(ProbeUpdate)
        live = select_live(live_rows())
        release.record = {"live": live, "inventory": {row["Id"]: row for row in live.values()}}
        release.events = []
        release.stop = lambda row: release.events.append(("stop", row["Id"]))
        release.start = lambda row: release.events.append(("start", row["Id"]))
        release.idle_workers = lambda rows: release.events.append("idle")
        release.rows = lambda: list(live.values())
        release.build_fast_images = lambda: {"backend": "synthetic", "frontend": "synthetic"}
        result = release.fast_images()
        self.assertEqual(result, {"backend": "synthetic", "frontend": "synthetic"})
        self.assertEqual(release.events[0], "before-super")
        self.assertEqual(release.events[1], ("stop", live["email-beat"]["Id"]))
        self.assertEqual(release.events[2], "idle")
        self.assertEqual(release.events[-1], "after-super")
        starts = {row[1] for row in release.events if isinstance(row, tuple) and row[0] == "start"}
        self.assertEqual(starts, {live[name]["Id"] for name in (*facade.WORKERS, "email-beat")})

    def test_cli_help_and_argument_errors_work_from_unrelated_directory(self):
        script = Path(facade.__file__).resolve()
        env = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT") if key in os.environ}
        env["PYTHONPATH"] = ""
        with tempfile.TemporaryDirectory() as directory:
            for args, status in [(["--help"], 0), (["--not-a-release-option"], 2)]:
                result = subprocess.run(
                    [sys.executable, "-B", str(script), *args],
                    cwd=directory,
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=10,
                )
                self.assertEqual(result.returncode, status, result.stderr)
                self.assertIn("--revision", result.stdout + result.stderr)

    def test_each_new_source_owner_is_required_in_existing_qualification(self):
        names = {
            f"scripts/retained_release_{part}.py"
            for part in ("contract", "fast", "host", "runtime", "build", "lifecycle")
        }
        self.assertLessEqual(names, set(resources.QUALIFIED_SOURCES))
        root = Path(__file__).resolve().parents[1]
        hashes = resources.qualified_source_hashes(root)
        self.assertEqual(set(hashes), set(resources.QUALIFIED_SOURCES))
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            for name in resources.QUALIFIED_SOURCES:
                path = target / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes((root / name).read_bytes())
            self.assertEqual(resources.qualified_source_hashes(target), hashes)
            changed = target / sorted(names)[0]
            changed.write_text("synthetic different source", encoding="utf-8")
            self.assertNotEqual(
                resources.qualified_source_hashes(target)[sorted(names)[0]],
                hashes[sorted(names)[0]],
            )
            changed.unlink()
            with self.assertRaises(FileNotFoundError):
                resources.qualified_source_hashes(target)


if __name__ == "__main__":
    unittest.main()
