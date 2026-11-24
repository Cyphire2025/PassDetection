"""Health probes use a retained PWA asset; subprocesses are local fake-fetch Node."""

import io
import json
import shutil
import subprocess
import unittest
from unittest.mock import Mock, patch

import release_code_update as code
import release_retained_update as retained
import retained_release_runtime as retained_runtime
from PIL import Image
from release_workspace_branding_policy import BASE, BASE_0141

ROOT = code.Path(__file__).resolve().parents[1]
ASSET = "/pwa-icon-192.png"
REVISION = "a" * 40


def exercise_node_probe(script, rejected=None):
    """Run the actual captured promise code, with no real HTTP fetch available."""
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Reviewed Node runtime is required")
    bootstrap = (
        "const urls=[];globalThis.fetch=async url=>{urls.push(url);"
        "if(!['http://127.0.0.1:3000/login','http://127.0.0.1:3000/pwa-icon-192.png'].includes(url))"
        "throw Error('unexpected probe target');"
        f"return{{status:url==={json.dumps(rejected)}?503:200}};}};"
        "process.on('exit',code=>{if(code===0&&urls.length!==2)process.exitCode=4;});"
    )
    return subprocess.run(
        [node, "-e", bootstrap + script],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )


class RetainedHealthAssetTests(unittest.TestCase):
    def test_current_and_both_release_sources_contain_valid_icon_and_runtime_copy(self):
        assets = [(ROOT / "frontend/public/pwa-icon-192.png").read_bytes()]
        for revision in (BASE, BASE_0141):
            assets.append(
                subprocess.check_output(
                    ["git", "show", f"{revision}:frontend/public/pwa-icon-192.png"],
                    cwd=ROOT,
                )
            )
            dockerfile = subprocess.check_output(
                ["git", "show", f"{revision}:frontend/Dockerfile"],
                cwd=ROOT,
            ).decode("utf-8")
            self.assertIn("COPY --from=builder /app/public ./public", dockerfile)
        for raw in assets:
            with self.subTest(size=len(raw)), Image.open(io.BytesIO(raw)) as image:
                self.assertEqual((image.format, image.size), ("PNG", (192, 192)))
                image.verify()

    def test_code_update_frontend_probe_preserves_success_and_failure_gates(self):
        release = object.__new__(code.CodeUpdate)
        release.run = Mock(return_value="")
        release.probe("synthetic-candidate", "frontend", REVISION)
        args, kwargs = release.run.call_args
        self.assertEqual(args[:5], ("docker", "exec", "synthetic-candidate", "node", "-e"))
        self.assertEqual(kwargs, {"timeout": 25})
        self.assert_node_cases(args[5])

    def test_retained_update_frontend_probe_preserves_success_and_failure_gates(self):
        release = object.__new__(retained.RetainedUpdate)
        release.revision = REVISION
        release.verify_assistant_transport = Mock()
        release.wait_health = Mock()
        release.retention = Mock()
        rows = {
            "backend": {"Id": "synthetic-backend"},
            "frontend": {
                "Id": "synthetic-frontend",
                "Config": {
                    "Env": [f"NEXT_PUBLIC_APP_REVISION={REVISION}"],
                },
            },
        }
        with (
            patch.object(retained_runtime, "command", return_value="") as command,
            patch.object(retained_runtime, "bound_original", side_effect=lambda row: row),
            patch.object(retained_runtime, "wait_full_readiness"),
        ):
            release.proof(rows, REVISION, public=False)
        release.wait_health.assert_called_once_with(rows)
        release.retention.assert_called_once_with()
        args = command.call_args.args
        self.assertEqual(args[:5], ("docker", "exec", "synthetic-frontend", "node", "-e"))
        self.assert_node_cases(args[5])

    def assert_node_cases(self, script):
        for rejected, expected in (
            (None, 0),
            ("http://127.0.0.1:3000/login", 1),
            ("http://127.0.0.1:3000" + ASSET, 1),
        ):
            result = exercise_node_probe(script, rejected)
            with self.subTest(rejected=rejected):
                self.assertEqual(result.returncode, expected, result.stderr)

    def test_public_probe_requires_both_original_routes_and_rejects_icon_failure(self):
        for icon_status in ("200", "503"):
            release = object.__new__(code.CodeUpdate)

            def command(*args):
                url = args[-1]
                if url.endswith("/api/v1/health/ready"):
                    return json.dumps({"revision": REVISION})
                if url.endswith("/login"):
                    return "200"
                if url.endswith(ASSET):
                    return icon_status
                return "404"

            release.run = Mock(side_effect=command)
            with patch.object(code, "validate_readiness") as validate:
                if icon_status == "200":
                    release.public_probe(REVISION, full=True)
                else:
                    with self.assertRaises(code.ReleaseError):
                        release.public_probe(REVISION, full=True)
            validate.assert_called_once_with({"revision": REVISION}, REVISION, full=True)
            self.assertEqual(len(release.run.call_args_list), 3)
            self.assertEqual(
                release.run.call_args_list[-1].args[-1], "https://tech.gctravels.com" + ASSET
            )


if __name__ == "__main__":
    unittest.main()
