"""First-install key custody and recovery; no real credentials or Docker access."""
from __future__ import annotations

import base64
import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from release_companies_secrets import (
    KEY_FILE,
    PREFIX,
    runtime_values,
    verify_configuration,
)
from release_companies_traveller_contract import SOURCE, TARGET


def container(name: str, values: dict[str, str] | None = None) -> dict:
    return {'Config': {'Labels': {'com.docker.compose.service': name},
                       'Env': [key + '=' + value for key, value in (values or {}).items()]}}


class ReuseRuntimeSecrets(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.record = {'schema': SOURCE, 'additive_release': True,
                       'live': {name: container(name) for name in ('backend', 'worker', 'email-beat')}}
        self.events = []

        def event(phase, **values):
            self.events.append({'phase': phase, **values})
            self.record.update(values)

        self.release = SimpleNamespace(directory=self.directory, record=self.record, event=event)

    def test_generated_keys_are_independent_private_and_reused_without_sensitive_receipts(self):
        values = runtime_values(self.release, self.record['live']['backend'])
        self.assertGreaterEqual(len(values[PREFIX + 'LOOKUP_KEY']), 32)
        self.assertEqual(len(base64.urlsafe_b64decode(values[PREFIX + 'ENCRYPTION_KEY'])), 32)
        self.assertNotEqual(values[PREFIX + 'LOOKUP_KEY'], values[PREFIX + 'ENCRYPTION_KEY'])
        self.assertEqual(values[PREFIX + 'DISCLOSURE_ENABLED'], 'true')
        self.assertEqual(runtime_values(self.release, self.record['live']['worker']), values)
        self.assertEqual(verify_configuration(self.release), values)
        self.assertEqual(len(self.events), 1)
        receipt = json.dumps(self.events)
        for key in ('LOOKUP_KEY', 'ENCRYPTION_KEY'):
            self.assertNotIn(values[PREFIX + key], receipt)
        self.assertTrue(self.events[0]['traveller_runtime_configuration']['company_group_and_person_permission_required'])

    def test_browser_and_proxy_never_receive_key_material(self):
        for name in ('frontend', 'nginx'):
            self.assertEqual(runtime_values(self.release, container(name)), {})
        self.assertFalse((self.directory / KEY_FILE).exists())

    def test_existing_complete_configuration_and_disabled_switch_are_preserved(self):
        existing = {PREFIX + 'LOOKUP_KEY': 'synthetic-' + 'a' * 40,
                    PREFIX + 'ENCRYPTION_KEY': base64.urlsafe_b64encode(b'c' * 32).decode(),
                    PREFIX + 'KEY_VERSION': 'existing-v2', PREFIX + 'DISCLOSURE_ENABLED': 'false'}
        self.record['live'] = {name: container(name, existing) for name in self.record['live']}
        self.assertEqual(runtime_values(self.release, self.record['live']['backend']), existing)
        self.assertFalse(self.events[0]['traveller_runtime_configuration']['new_keys_provisioned'])

    def test_partial_or_inconsistent_service_configuration_is_rejected_before_any_write(self):
        original = copy.deepcopy(self.record['live'])
        for values in ({PREFIX + 'DISCLOSURE_ENABLED': 'false'},
                       {PREFIX + 'KEY_VERSION': 'existing-v2'},
                       {PREFIX + 'LOOKUP_KEY': 'a' * 40},
                       {PREFIX + 'LOOKUP_KEY': 'a' * 40,
                        PREFIX + 'ENCRYPTION_KEY': base64.urlsafe_b64encode(b'c' * 32).decode()}):
            self.record['live'] = copy.deepcopy(original)
            self.record['live']['backend'] = container('backend', values)
            with self.assertRaises(ValueError):
                runtime_values(self.release, self.record['live']['backend'])
            self.assertFalse((self.directory / KEY_FILE).exists())

    def test_target_schema_never_generates_new_keys(self):
        self.record['schema'] = TARGET
        with self.assertRaisesRegex(ValueError, 'first_install'):
            runtime_values(self.release, self.record['live']['backend'])

    def test_changed_or_missing_retained_keys_stop_recovery(self):
        runtime_values(self.release, self.record['live']['backend'])
        path = self.directory / KEY_FILE
        path.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'binding_changed'):
            verify_configuration(self.release)
        path.unlink()
        with self.assertRaises(FileNotFoundError):
            runtime_values(self.release, self.record['live']['backend'])
        self.assertFalse(path.exists())

    def test_orphan_private_key_file_is_never_overwritten(self):
        path = self.directory / KEY_FILE
        path.write_text('retained operator evidence')
        with self.assertRaises(FileExistsError):
            runtime_values(self.release, self.record['live']['backend'])
        self.assertEqual(path.read_text(), 'retained operator evidence')


if __name__ == '__main__':
    unittest.main()
