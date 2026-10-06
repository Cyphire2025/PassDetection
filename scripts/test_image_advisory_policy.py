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
        accepted = validate_policy(policy, dt.date(2026, 10, 6))
        self.assertNotIn(("CVE-2026-82049", "python", "3.11.17"), accepted)
        self.assertNotIn(("CVE-NEW", "python", "3.11.16"), accepted)
        for changes in ({"owner": ""}, {"evidence": []}, {"condition": ""},
                        {"expires_on": "2026-09-26"}, {"reviewed_on": "2026-10-07"},
                        {"expires_on": "2027-09-27"}, {"disposition": "wontfix"},
                        {"advisory": "CVE-NEW"}):
            changed = copy.deepcopy(policy)
            changed["entries"][0].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_policy(changed, dt.date(2026, 10, 6))

    def test_gcc_dispositions_are_exact_tuples_and_time_bounded(self):
        policy = json.loads((Path(__file__).resolve().parents[1] / "tooling/image-advisory-dispositions.json").read_text())
        accepted = validate_policy(policy, dt.date(2026, 10, 6))
        gcc_ids = {"CVE-2026-95619", "CVE-2026-102010"}
        expected = {(cve, name, "14.2.0-19") for cve in gcc_ids
                    for name in ("gcc-14-base", "libgcc-s1", "libgomp1", "libstdc++6")}
        self.assertEqual({item for item in accepted if item[0] in gcc_ids}, expected)
        for cve in gcc_ids:
            self.assertNotIn((cve, "libstdc++-14-dev", "14.2.0-19"), accepted)
            self.assertNotIn((cve, "libstdc++6", "14.2.0-20"), accepted)
        only_gcc = {**policy, "entries": [entry for entry in policy["entries"] if entry["advisory"] in gcc_ids]}
        with self.assertRaisesRegex(ValueError, "expired"):
            validate_policy(only_gcc, dt.date(2026, 11, 5))
        for entry_index in range(2):
            for package in ({"name": "libstdc++-14-dev", "version": "14.2.0-19"},
                            {"name": "libstdc++6", "version": "14.2.0-20"}):
                changed = copy.deepcopy(only_gcc)
                changed["entries"][entry_index]["packages"].append(package)
                with self.subTest(index=entry_index, package=package), self.assertRaisesRegex(ValueError, "package scope"):
                    validate_policy(changed, dt.date(2026, 10, 6))


if __name__ == "__main__":
    unittest.main()
