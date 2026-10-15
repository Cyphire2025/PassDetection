"""Refuse inherited, missing, mixed or incompletely installed security patches."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "runtime_security_packages", ROOT / "backend/docker/verify_runtime_security_packages.py",
)
assert SPEC and SPEC.loader
verification = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verification)


class RuntimeSecurityPackagesTests(unittest.TestCase):
    def setUp(self):
        self.pins = json.loads(verification.PINS.read_text(encoding="utf-8"))
        self.installed = {name: f"{name}\t{version}\tinstall ok installed" for name, version in self.pins.items()}

    def test_exact_patches_are_accepted_independent_of_dpkg_output_order(self):
        output = "\n".join(reversed(list(self.installed.values()))) + "\n"
        self.assertEqual(verification.verify_packages(self.pins, output), self.pins)

    def test_each_inherited_vulnerable_package_is_rejected_among_other_patched_packages(self):
        for name in self.pins:
            rows = dict(self.installed)
            rows[name] = rows[name].replace("deb13u3", "deb13u2")
            with self.subTest(package=name), self.assertRaisesRegex(ValueError, "reviewed patch"):
                verification.verify_packages(self.pins, "\n".join(rows.values()))

    def test_missing_duplicate_or_not_installed_package_cannot_pass(self):
        rows = list(self.installed.values())
        for output in ("\n".join(rows[1:]), "\n".join([*rows, rows[0]]),
                       "\n".join(rows).replace("install ok installed", "deinstall ok config-files", 1),
                       "\n".join(rows) + "\nunexpected\t1\tinstall ok installed", "malformed"):
            with self.subTest(output=output), self.assertRaises(ValueError):
                verification.verify_packages(self.pins, output)

    def test_runtime_readback_queries_every_pin_and_propagates_dpkg_failures(self):
        output = "\n".join(self.installed.values())
        with patch.object(verification.subprocess, "check_output", return_value=output) as query, \
                patch("builtins.print") as printed:
            verification.main()
        self.assertEqual(set(query.call_args.args[0][3:]), set(self.pins))
        self.assertEqual(json.loads(printed.call_args.args[0]), {"debian_security_packages": self.pins})
        with patch.object(verification.subprocess, "check_output", side_effect=subprocess.CalledProcessError(1, [])), \
                self.assertRaises(subprocess.CalledProcessError):
            verification.main()
