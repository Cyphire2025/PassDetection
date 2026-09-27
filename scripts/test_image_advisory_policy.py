import base64
import copy
import datetime as dt
import hashlib
import json
import unittest
from pathlib import Path

from image_advisory_policy import validate_policy, validate_report_identity


class ImageAdvisoryTests(unittest.TestCase):
    def test_exact_image_bytes_and_configuration_required(self):
        config = {"config": {"User": "appuser"}, "rootfs": {"diff_ids": ["sha256:one"]},
                  "architecture": "amd64", "os": "linux"}
        raw = json.dumps(config).encode()
        identifier = "sha256:" + hashlib.sha256(raw).hexdigest()
        report = {"source": {"target": {"config": base64.b64encode(raw).decode(), "imageID": identifier}}}
        inspected = {"Config": config["config"], "RootFS": {"Layers": ["sha256:one"]},
                     "Architecture": "amd64", "Os": "linux"}
        self.assertEqual(validate_report_identity(report, inspected), identifier)
        for changes in ({"Config": {"User": "root"}}, {"RootFS": {"Layers": ["sha256:other"]}}, {"Architecture": "arm64"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_report_identity(report, {**inspected, **changes})
        report["source"]["target"]["imageID"] = "sha256:wrong"
        with self.assertRaises(ValueError):
            validate_report_identity(report, inspected)

    def test_scanner_identity_accepts_legacy_inspect_defaults_without_changing_digest(self):
        config = {"config": {"User": "appuser", "Labels": {"revision": "qualified"}},
                  "rootfs": {"diff_ids": ["sha256:one"]}, "architecture": "amd64", "os": "linux"}
        raw = json.dumps(config).encode()
        identifier = "sha256:" + hashlib.sha256(raw).hexdigest()
        report = {"source": {"target": {"config": base64.b64encode(raw).decode(), "imageID": identifier}}}
        inspected = {"Config": {**config["config"], "AttachStdin": False, "Hostname": "",
                                "Cmd": None, "Entrypoint": None, "OnBuild": None, "Volumes": None},
                     "RootFS": {"Layers": ["sha256:one"]}, "Architecture": "amd64", "Os": "linux"}
        self.assertEqual(validate_report_identity(report, inspected), identifier)
        for change in ({"User": "root"}, {"Entrypoint": ["changed"]}, {"UnknownField": None}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_report_identity(report, {**inspected, "Config": {**inspected["Config"], **change}})
        report["source"]["target"]["imageID"] = "sha256:" + "0" * 64
        with self.assertRaises(ValueError):
            validate_report_identity(report, inspected)

    def test_review_expiry_owner_and_exact_versions(self):
        policy = json.loads((Path(__file__).resolve().parents[1] / "tooling/image-advisory-dispositions.json").read_text())
        accepted = validate_policy(policy, dt.date(2026, 9, 27))
        self.assertNotIn(("CVE-2026-82049", "python", "3.11.17"), accepted)
        self.assertNotIn(("CVE-NEW", "python", "3.11.16"), accepted)
        for changes in ({"owner": ""}, {"evidence": []}, {"condition": ""},
                        {"expires_on": "2026-09-26"}, {"reviewed_on": "2026-10-01"},
                        {"expires_on": "2027-09-27"}, {"disposition": "wontfix"},
                        {"advisory": "CVE-NEW"}):
            changed = copy.deepcopy(policy)
            changed["entries"][0].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_policy(changed, dt.date(2026, 9, 27))


if __name__ == "__main__":
    unittest.main()
