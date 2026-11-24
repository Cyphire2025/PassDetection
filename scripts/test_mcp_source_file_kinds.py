"""Source inventory file-kind contract, with no release or service operations."""

import hashlib
import os
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from mcp_direct_build import BuildError
from mcp_direct_state import source_inventory


class SourceFileKinds(unittest.TestCase):
    def test_real_regular_files_and_directories_keep_exact_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "nested").mkdir()
            (root / "alpha.py").write_bytes(b"synthetic-alpha")
            (root / "nested/beta.py").write_bytes(b"synthetic-beta")
            self.assertEqual(
                source_inventory(root),
                {
                    "alpha.py": hashlib.sha256(b"synthetic-alpha").hexdigest(),
                    "nested/beta.py": hashlib.sha256(b"synthetic-beta").hexdigest(),
                },
            )

    def source(self, entry):
        root = Mock(spec=Path)
        root.is_symlink.return_value = False
        root.is_dir.return_value = True
        root.resolve.return_value = root
        root.rglob.return_value = [entry]
        return root

    def test_nonregular_nondirectory_kind_is_rejected_before_reading(self):
        for kind in (stat.S_IFIFO, stat.S_IFSOCK, stat.S_IFCHR, stat.S_IFBLK):
            with self.subTest(kind=kind):
                entry = Mock(spec=Path)
                entry.is_symlink.return_value = False
                entry.is_dir.return_value = False
                entry.is_file.return_value = False
                entry.stat.return_value = SimpleNamespace(st_mode=kind | 0o600)
                with self.assertRaisesRegex(BuildError, "^source_special_file_forbidden$"):
                    source_inventory(self.source(entry))
                entry.read_bytes.assert_not_called()

    def test_existing_symlink_rejection_remains_authoritative(self):
        entry = Mock(spec=Path)
        entry.is_symlink.return_value = True
        with self.assertRaisesRegex(BuildError, "^source_alias_forbidden$"):
            source_inventory(self.source(entry))
        entry.read_bytes.assert_not_called()

    @unittest.skipUnless(
        hasattr(os, "mkfifo"), "Actual FIFO control requires the POSIX deployment platform"
    )
    def test_actual_posix_fifo_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            os.mkfifo(root / "synthetic.pipe", 0o600)
            with self.assertRaisesRegex(BuildError, "^source_special_file_forbidden$"):
                source_inventory(root)


if __name__ == "__main__":
    unittest.main()
