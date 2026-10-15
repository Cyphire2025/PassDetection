"""Native client source integrity and negative linkage/authentication boundaries."""
from __future__ import annotations

import hashlib
import importlib.util
import io
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def load_helper(name: str):
    path = Path(__file__).resolve().parents[1] / "backend/docker" / (name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build = load_helper("build_postgresql_client")
probe = load_helper("verify_postgresql_client")


class NativeSourceTests(unittest.TestCase):
    def test_runtime_stage_excludes_build_artifacts_and_preserves_native_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "libpq.so.5").write_bytes(b"reviewed-native-library")
            (source / "libpq.a").write_bytes(b"build-only-static-library")
            (source / "unrelated.so").write_bytes(b"unrelated")
            target = root / "runtime"
            build.stage_runtime_libraries(source, target)
            self.assertEqual([path.name for path in target.iterdir()], ["libpq.so.5"])
            probe.verify_inventory((target,), target / "libpq.so.5")

    def test_runtime_stage_keeps_symlinks_accepted_by_strict_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "libpq.so.5.17").write_bytes(b"reviewed-native-library")
            try:
                (source / "libpq.so.5").symlink_to("libpq.so.5.17")
                (source / "libpq.so").symlink_to("libpq.so.5")
            except OSError:
                self.skipTest("Host does not permit creating filesystem symlinks")
            target = root / "runtime"
            build.stage_runtime_libraries(source, target)
            self.assertTrue((target / "libpq.so.5").is_symlink())
            self.assertTrue((target / "libpq.so").is_symlink())
            probe.verify_inventory((target,), target / "libpq.so.5")

    def test_exact_source_bytes_admitted_and_changed_bytes_rejected(self):
        content = b"reviewed-source-fixture"
        entry = {"url": "https://invalid.example/source", "sha256": hashlib.sha256(content).hexdigest()}
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "source.tar"
            with patch.object(build.urllib.request, "urlopen", return_value=io.BytesIO(content)) as fetch:
                build.download(entry, target)
            self.assertEqual(target.read_bytes(), content)
            fetch.assert_called_once_with(entry["url"], timeout=60)
            with patch.object(build.urllib.request, "urlopen", return_value=io.BytesIO(b"modified")), \
                    self.assertRaisesRegex(RuntimeError, "checksum"):
                build.download(entry, Path(directory) / "modified.tar")

    def test_download_is_bounded_and_cannot_overwrite_an_existing_input(self):
        entry = {"url": "https://invalid.example/source", "sha256": "0" * 64}
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "source.tar"
            with patch.object(build, "MAX_SOURCE_BYTES", 4), patch.object(
                build.urllib.request, "urlopen", return_value=io.BytesIO(b"too-large")
            ), self.assertRaisesRegex(RuntimeError, "budget"):
                build.download(entry, target)
            self.assertEqual(target.read_bytes(), b"")
            with patch.object(build.urllib.request, "urlopen", return_value=io.BytesIO(b"x")), \
                    self.assertRaises(FileExistsError):
                build.download(entry, target)


class NativeLinkageTests(unittest.TestCase):
    def test_exact_library_with_openssl_is_accepted(self):
        library = Path("/reviewed/libpq.so.5")
        probe.verify_linkage(f"libpq.so.5 => {library}\nlibssl.so.3 => /ssl\nlibcrypto.so.3 => /crypto", library)

    def test_missing_duplicate_private_or_unneeded_dependencies_are_rejected(self):
        library = Path("/reviewed/libpq.so.5")
        correct = f"libpq.so.5 => {library}\nlibssl.so.3 => /ssl\nlibcrypto.so.3 => /crypto"
        invalid = [
            correct + "\nlibgssapi_krb5.so.2 => /gss",
            correct + "\nlibldap.so.2 => /ldap",
            correct + "\nlibsasl2.so.2 => /sasl",
            correct + "\nlibother.so.1 => not found",
            correct + "\nlibpq-private.so.5 => /wheel/libpq-private.so.5",
            correct.replace(str(library), "/wheel/libpq.so.5"),
            correct.replace("libssl.so.3", "unused.so.3"),
        ]
        for linkage in invalid:
            with self.subTest(linkage=linkage), self.assertRaises(RuntimeError):
                probe.verify_linkage(linkage, library)

    def test_inventory_detects_unloaded_private_copies(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            library = root / "libpq.so.5"
            library.write_bytes(b"admitted")
            probe.verify_inventory((root,), library)
            private = root / "private"
            private.mkdir()
            hidden = private / "libpq-private.so.5"
            hidden.write_bytes(b"unloaded")
            with self.assertRaisesRegex(RuntimeError, "bundled"):
                probe.verify_inventory((root,), library)
            hidden.unlink()
            (private / "libkrb5support.so.0").write_bytes(b"unloaded")
            with self.assertRaisesRegex(RuntimeError, "authentication"):
                probe.verify_inventory((root,), library)


class DatabaseProbeTests(unittest.TestCase):
    def test_probe_requires_scram_verified_tls_and_channel_binding(self):
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.info.ssl_in_use = True
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = ("synthetic-round-trip",)
        driver = SimpleNamespace(connect=MagicMock(return_value=connection))
        environment = {"POSTGRES_HOST": "fixture", "POSTGRES_DB": "fixture", "POSTGRES_USER": "fixture",
                       "POSTGRES_PASSWORD": "synthetic-test-password", "PGSSLROOTCERT": "/fixture/ca.crt"}
        with patch.dict("sys.modules", psycopg2=driver), patch.dict(os.environ, environment, clear=True):
            result = probe.database_probe(require_tls=True)
        parameters = driver.connect.call_args.kwargs
        self.assertEqual(parameters["require_auth"], "scram-sha-256")
        self.assertEqual(parameters["sslmode"], "verify-full")
        self.assertEqual(parameters["channel_binding"], "require")
        self.assertEqual(parameters["sslrootcert"], "/fixture/ca.crt")
        self.assertEqual(parameters["connect_timeout"], "10")
        self.assertTrue(result["tls_hostname_and_chain_verified"])
        self.assertNotIn("synthetic-test-password", str(result))

    def test_failed_connection_is_not_retried_with_weaker_authentication(self):
        driver = SimpleNamespace(connect=MagicMock(side_effect=RuntimeError("synthetic CA rejection")))
        environment = {"POSTGRES_HOST": "fixture", "POSTGRES_DB": "fixture", "POSTGRES_USER": "fixture",
                       "POSTGRES_PASSWORD": "synthetic-test-password", "PGSSLROOTCERT": "/fixture/wrong.crt"}
        with patch.dict("sys.modules", psycopg2=driver), patch.dict(os.environ, environment, clear=True), \
                self.assertRaisesRegex(RuntimeError, "CA rejection"):
            probe.database_probe(require_tls=True)
        driver.connect.assert_called_once()


if __name__ == "__main__":
    unittest.main()
