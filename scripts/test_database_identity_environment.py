"""Credential preparation is idempotent and preserves all existing data settings."""

import unittest

from database_identity_environment import prepare_database_identity_environment


class DatabaseIdentityEnvironmentTests(unittest.TestCase):
    def test_preserves_bootstrap_and_independent_secrets_on_retry(self):
        original = "# existing production settings\nPOSTGRES_USER=old_admin\nPOSTGRES_PASSWORD='old/@%secret'\nS3_BUCKET_NAME=original\n"
        prepared = prepare_database_identity_environment(original)
        self.assertTrue(prepared.startswith(original))
        self.assertEqual(prepare_database_identity_environment(prepared), prepared)
        values = dict(line.split("=", 1) for line in prepared.splitlines() if "=" in line)
        self.assertNotEqual(values["POSTGRES_RUNTIME_PASSWORD"], values["POSTGRES_MIGRATION_PASSWORD"])
        self.assertGreaterEqual(len(values["POSTGRES_RUNTIME_PASSWORD"]), 48)

    def test_replaces_only_blank_or_example_role_values(self):
        source = "POSTGRES_RUNTIME_USER=custom_role\nPOSTGRES_RUNTIME_PASSWORD='existing-secret'\nPOSTGRES_MIGRATION_USER=\nPOSTGRES_MIGRATION_PASSWORD=CHANGE_ME_MIGRATION_SECRET\n"
        result = prepare_database_identity_environment(source)
        self.assertIn("POSTGRES_RUNTIME_USER=custom_role\nPOSTGRES_RUNTIME_PASSWORD='existing-secret'", result)
        self.assertNotIn("CHANGE_ME_", result)
        self.assertIn("POSTGRES_MIGRATION_USER=passdetection_migrator", result)

    def test_rejects_duplicate_identity_keys(self):
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            prepare_database_identity_environment("POSTGRES_RUNTIME_USER=a\nPOSTGRES_RUNTIME_USER=b\n")


if __name__ == "__main__":
    unittest.main()
