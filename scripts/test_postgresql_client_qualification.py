import json
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from qa import qualify_postgresql_client as qualification
from qa.postgres_tls_fixture import create_tls_fixture


def result(code=0, output="", error=""):
    return subprocess.CompletedProcess(["docker"], code, output, error)


class PostgreSQLQualificationTests(unittest.TestCase):
    def test_private_key_permissions_are_set_before_root_relinquishes_ownership(self):
        with patch.object(qualification, "run", return_value=result()) as command:
            qualification.create_server("synthetic-db", "synthetic-network", "owner", Path("fixture"))
        arguments = command.call_args_list[0].args[0]
        self.assertEqual(arguments[arguments.index("--cap-drop") + 1], "ALL")
        capabilities = {arguments[index + 1] for index, value in enumerate(arguments) if value == "--cap-add"}
        self.assertNotIn("FOWNER", capabilities)
        self.assertNotIn("ALL", capabilities)
        operations = [shlex.split(operation) for operation in arguments[-1].split(";") if operation.strip()]
        chmod = next(index for index, operation in enumerate(operations)
                     if operation[0] == "chmod" and operation[-1] == "/run/pg-tls/server.key")
        chown = next(index for index, operation in enumerate(operations) if operation[0] == "chown")
        self.assertEqual(operations[chmod][1], "600")
        self.assertLess(chmod, chown, "Root lacks CAP_FOWNER after assigning the key to postgres")

    def test_wrong_ca_requires_the_actual_certificate_failure(self):
        qualification.require_wrong_ca_rejection(result(1, error="SSL error: certificate verify failed"))
        for response in (result(), result(1, error="connection refused"), result(137, error="killed")):
            with self.subTest(response=response.returncode), self.assertRaises(qualification.QualificationError):
                qualification.require_wrong_ca_rejection(response)

    def test_command_failures_and_timeouts_never_expose_captured_secrets(self):
        secret = "synthetic-password-must-not-appear"
        for error in (None, subprocess.TimeoutExpired(["docker"], 3, output=secret, stderr=secret)):
            with patch.object(qualification.subprocess, "run", return_value=result(1, error=secret), side_effect=error):
                with self.assertRaises(qualification.QualificationError) as raised:
                    qualification.run(["docker", "start", "synthetic"], timeout=3)
                self.assertNotIn(secret, str(raised.exception))

    def test_success_requires_every_condition_and_strips_unapproved_fields(self):
        source = json.loads((qualification.ROOT / "backend/docker/postgresql_client_build.json").read_text())
        proof = {"status": "passed", "libpq_version": source["libpq_version"],
                 "source_sha256": source["source"]["sha256"], "libpq_sha256": "a" * 64,
                 "openssl_linked": True, "unneeded_auth_libraries_absent": True,
                 "bundled_driver_libraries_absent": True, "scram_authentication": True,
                 "database_round_trip": True, "tls_in_use": True, "tls_hostname_and_chain_verified": True,
                 "unexpected_password": "must-not-appear"}
        safe = qualification.validate_success(result(output=json.dumps(proof)))
        self.assertNotIn("unexpected_password", safe)
        for changes in ({"tls_in_use": False}, {"scram_authentication": 1}, {"libpq_version": 160000},
                        {"source_sha256": "b" * 64}, {"libpq_sha256": ""}):
            with self.subTest(changes=changes), self.assertRaises(qualification.QualificationError):
                qualification.validate_success(result(output=json.dumps({**proof, **changes})))
        with self.assertRaises(qualification.QualificationError):
            qualification.validate_success(result(output="not JSON"))

    def test_wrong_image_revision_fails_before_any_service_starts(self):
        details = [{"Id": "sha256:" + "a" * 64, "Config": {"Labels": {"org.opencontainers.image.revision": "b" * 40}}}]
        with patch.object(qualification, "run", return_value=result(output=json.dumps(details))) as command:
            with self.assertRaisesRegex(qualification.QualificationError, "source revision"):
                qualification.inspect_image("synthetic-image", "a" * 40)
            self.assertEqual(command.call_count, 1)

    def test_foreign_resource_is_never_removed(self):
        value = [{"Config": {"Labels": {qualification.OWNER_LABEL: "other-owner"}}}]
        with patch.object(qualification, "run", return_value=result(output=json.dumps(value))) as command:
            with self.assertRaisesRegex(qualification.QualificationError, "another invocation"):
                qualification.remove_owned("container", "synthetic", "this-owner")
            self.assertEqual(command.call_count, 1)

    def test_cleanup_removes_only_the_inspected_immutable_resource(self):
        for kind in ("container", "network"):
            labels = {qualification.OWNER_LABEL: "this-owner"}
            value = {"Id": "a" * 64, "Labels": labels, "Config": {"Labels": labels}}
            with self.subTest(kind=kind), patch.object(qualification, "run", side_effect=[result(output=json.dumps([value])), result()]) as command:
                qualification.remove_owned(kind, "generated-name", "this-owner")
                self.assertEqual(command.call_args.args[0][-1], "a" * 64)
                self.assertNotIn("generated-name", command.call_args.args[0])

    def test_partial_startup_failure_cleans_every_pre_registered_owned_resource(self):
        with (
            patch.object(qualification, "inspect_image", return_value="sha256:" + "a" * 64),
            patch.object(qualification, "run", return_value=result()),
            patch.object(qualification, "create_tls_fixture"),
            patch.object(qualification, "create_server", side_effect=qualification.QualificationError("startup failed")),
            patch.object(qualification, "remove_owned") as cleanup,
            self.assertRaisesRegex(qualification.QualificationError, "startup failed"),
        ):
            qualification.qualify("synthetic-image", "a" * 40)
        self.assertEqual(cleanup.call_count, 4)
        owners = {call.args[2] for call in cleanup.call_args_list}
        self.assertEqual(len(owners), 1)
        owner = owners.pop()
        self.assertTrue(all(call.args[1].startswith("pd-native-pg-" + owner) for call in cleanup.call_args_list))
        self.assertEqual(cleanup.call_args_list[-1].args[0], "network")

    def test_readiness_failure_is_bounded(self):
        with patch.object(qualification, "run", return_value=result(1)) as command:
            with self.assertRaisesRegex(qualification.QualificationError, "deadline"):
                qualification.wait_ready("synthetic", deadline_seconds=0)
            self.assertEqual(command.call_count, 1)

    def test_certificates_match_the_private_hostname_and_use_distinct_trust_roots(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            hostname = "pd-native-pg-synthetic-db"
            create_tls_fixture(root, hostname)
            server = x509.load_pem_x509_certificate((root / "server/server.crt").read_bytes())
            trusted = x509.load_pem_x509_certificate((root / "trusted/ca.crt").read_bytes())
            untrusted = x509.load_pem_x509_certificate((root / "untrusted/ca.crt").read_bytes())
            server.verify_directly_issued_by(trusted)
            self.assertEqual(server.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.DNSName), [hostname])
            self.assertNotEqual(trusted.fingerprint(hashes.SHA256()), untrusted.fingerprint(hashes.SHA256()))
            with self.assertRaises(ValueError):
                server.verify_directly_issued_by(untrusted)


if __name__ == "__main__":
    unittest.main()
