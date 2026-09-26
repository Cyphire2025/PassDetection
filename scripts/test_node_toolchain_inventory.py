import json
import tempfile
import unittest
from pathlib import Path

from inventory_npm_toolchain import inventory


class InstallerInventoryTests(unittest.TestCase):
    def test_missing_bundled_packages_cannot_be_reported_as_a_clean_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "package.json").write_text(json.dumps({"name": "npm", "version": "11.20.0"}))
            with self.assertRaisesRegex(ValueError, "incomplete"):
                inventory(root, "11.20.0")

    def test_installed_version_drift_is_refused_before_cataloguing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "package.json").write_text(json.dumps({"name": "npm", "version": "11.19.0"}))
            with self.assertRaisesRegex(ValueError, "differs"):
                inventory(root, "11.20.0")


if __name__ == "__main__":
    unittest.main()
