"""Synthetic credential custody and preflight tests; no Docker/production access."""
from __future__ import annotations

import copy
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import release_companies_credentials as credentials
from release_companies_runtime import (
    bound_migration_helper,
    helper_binding,
    helper_payload,
)
from test_release_companies_retained_update import release_fixture


def container(identifier, user, password):
    return {'Id': identifier, 'Image': 'sha256:' + '1' * 64, 'HostConfig': {}, 'Mounts': [],
            'Config': {'Env': ['POSTGRES_USER=' + user, 'POSTGRES_PASSWORD=' + password, 'POSTGRES_DB=app']},
            'NetworkSettings': {'Networks': {'retained-net': {'IPAddress': '172.20.0.4'}}},
            'State': {'Running': True}}


class ExistingMigrationCredentials(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.values = {'POSTGRES_USER': 'existing_migrator', 'POSTGRES_PASSWORD': 'synthetic-migrator@:/漢字',
                       'POSTGRES_DB': 'app'}
        self.record = {'live': {'db': container('database-id', 'bootstrap', 'synthetic-admin'),
                                'backend': container('backend-id', 'runtime', 'synthetic-runtime')}}
        self.events = []

        def event(phase, **values):
            self.events.append({'phase': phase, **values})
            self.record.update(values)

        self.release = SimpleNamespace(directory=self.directory, source=self.directory / 'source', revision='a' * 40,
                                       record=self.record, event=event)
        self.compose = self.enterContext(patch.object(credentials, 'capture', side_effect=lambda *a, **kw: json.dumps(
            {'services': {'database-migrate': {'environment': self.values}}})))
        self.enterContext(patch.object(credentials, 'bound_original', side_effect=lambda row: row))
        self.process = self.enterContext(patch.object(credentials.subprocess, 'run', return_value=SimpleNamespace(
            returncode=0, stdout=b'{"owner_verified":true,"runtime_default_grants_verified":true}')))

    def prepare(self):
        credentials.prepare_migration_credentials(self.release)
        credentials.preflight_migration_credentials(self.release)

    def test_existing_migrator_selected_and_secrets_only_in_private_custody(self):
        self.prepare()
        values = credentials.migration_environment(self.release)
        self.assertEqual(values, {**self.values, 'POSTGRES_HOST': '172.20.0.4', 'POSTGRES_PORT': '5432'})
        self.assertEqual(json.loads((self.directory / credentials.CREDENTIAL_FILE).read_bytes()), self.values)
        self.assertNotIn(self.values['POSTGRES_PASSWORD'], json.dumps(self.events, ensure_ascii=False))
        self.assertNotIn('POSTGRES_PASSWORD', json.dumps(self.events))
        argv = self.compose.call_args.args[0]
        self.assertIn(str(credentials.ROOT / '.env'), argv)
        self.assertEqual(argv[-4:], ['maintenance', 'config', '--format', 'json'])
        credentials.prepare_migration_credentials(self.release)
        self.assertEqual(len(self.events), 2)

    def test_bootstrap_runtime_and_migrator_must_have_distinct_names_and_passwords(self):
        for key, value in [('POSTGRES_USER', 'bootstrap'), ('POSTGRES_USER', 'runtime'),
                           ('POSTGRES_PASSWORD', 'synthetic-admin'), ('POSTGRES_PASSWORD', 'synthetic-runtime')]:
            original = self.values[key]
            self.values[key] = value
            with self.subTest(key=key, value=value), self.assertRaisesRegex(ValueError, 'identity_must_be_distinct'):
                credentials.prepare_migration_credentials(self.release)
            self.values[key] = original
        self.assertFalse((self.directory / credentials.CREDENTIAL_FILE).exists())

    def test_missing_wrong_database_and_oversized_compose_credentials_fail_before_write(self):
        for values in ({}, {**self.values, 'POSTGRES_DB': 'other'},
                       {**self.values, 'POSTGRES_PASSWORD': 'x' * 4097}):
            self.values = values
            with self.subTest(values=list(values)), self.assertRaises(ValueError):
                credentials.prepare_migration_credentials(self.release)
        self.assertFalse((self.directory / credentials.CREDENTIAL_FILE).exists())

    def test_compose_drift_and_private_file_changes_stop_reuse(self):
        self.prepare()
        self.values['POSTGRES_PASSWORD'] = 'new-secret'
        with self.assertRaisesRegex(ValueError, 'credentials_drift'):
            credentials.migration_environment(self.release)
        (self.directory / credentials.CREDENTIAL_FILE).write_text('{}')
        with self.assertRaisesRegex(ValueError, 'credentials_changed'):
            credentials.migration_environment(self.release)

    def test_source_or_original_identity_drift_is_rejected(self):
        self.prepare()
        for target, key, changed in [(self.release, 'revision', 'b' * 40),
                                     (self.release, 'source', self.directory / 'other')]:
            original = getattr(target, key)
            setattr(target, key, changed)
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'source_binding_changed'):
                credentials.verify_migration_credentials(self.release)
            setattr(target, key, original)
        self.record['live']['db']['Id'] = 'replacement-id'
        with self.assertRaisesRegex(ValueError, 'source_binding_changed'):
            credentials.verify_migration_credentials(self.release)

    def test_current_endpoint_drift_and_multiple_shared_networks_fail_closed(self):
        self.prepare()
        changed = copy.deepcopy(self.record['live']['db'])
        changed['NetworkSettings']['Networks']['retained-net']['IPAddress'] = '172.20.0.5'
        with patch.object(credentials, 'bound_original', side_effect=lambda row: changed if row['Id'] == 'database-id' else row), \
                self.assertRaisesRegex(ValueError, 'endpoint_changed'):
            credentials.verify_migration_credentials(self.release)
        for row in self.record['live'].values():
            row['NetworkSettings']['Networks']['other-net'] = {'IPAddress': '172.21.0.1'}
        with self.assertRaisesRegex(ValueError, 'network_binding_ambiguous'):
            credentials.database_endpoint(self.record['live']['backend'], self.record['live']['db'])

    def test_orphan_and_missing_files_are_never_replaced(self):
        path = self.directory / credentials.CREDENTIAL_FILE
        path.write_text('operator evidence')
        with self.assertRaises(FileExistsError):
            credentials.prepare_migration_credentials(self.release)
        self.assertEqual(path.read_text(), 'operator evidence')
        path.unlink()
        self.prepare()
        path.unlink()
        with self.assertRaises(FileNotFoundError):
            credentials.prepare_migration_credentials(self.release)
        self.assertFalse(path.exists())

    def test_private_reader_rejects_oversized_symlink_hardlink_and_open_permissions(self):
        path = self.directory / credentials.CREDENTIAL_FILE
        path.write_bytes(b'x' * (credentials.MAXIMUM_BYTES + 1))
        with self.assertRaisesRegex(ValueError, 'file_invalid'):
            credentials.read_private(path)
        path.write_bytes(b'{}')
        with patch.object(Path, 'is_symlink', return_value=True), self.assertRaisesRegex(ValueError, 'file_invalid'):
            credentials.read_private(path)
        info = os.stat(path)
        with patch.object(credentials.os, 'fstat', return_value=SimpleNamespace(st_mode=info.st_mode, st_nlink=2, st_size=2)), \
                self.assertRaisesRegex(ValueError, 'file_invalid'):
            credentials.read_private(path)
        with patch.object(credentials, 'os', wraps=os) as fake:
            fake.name = 'posix'
            fake.geteuid = Mock(return_value=1000)
            fake.fstat.return_value = SimpleNamespace(st_mode=0o100644, st_nlink=1, st_size=2, st_uid=1000)
            with self.assertRaisesRegex(ValueError, 'file_permissions'):
                credentials.read_private(path)
            fake.fstat.return_value = SimpleNamespace(st_mode=0o100600, st_nlink=1, st_size=2, st_uid=1001)
            with self.assertRaisesRegex(ValueError, 'file_permissions'):
                credentials.read_private(path)

    def test_preflight_uses_stdin_and_bounded_readonly_connection_without_secret_argv(self):
        self.prepare()
        args, kwargs = self.process.call_args
        self.assertEqual(args[0][:4], ['docker', 'exec', '-i', 'backend-id'])
        self.assertNotIn(self.values['POSTGRES_PASSWORD'], str(args))
        self.assertEqual(json.loads(kwargs['input'])['POSTGRES_PASSWORD'], self.values['POSTGRES_PASSWORD'])
        self.assertEqual(kwargs['timeout'], 25)
        self.assertIn('default_transaction_read_only=on', credentials.PREFLIGHT)
        self.assertIn('statement_timeout=5000', credentials.PREFLIGHT)
        self.assertIn('required EXCEPT SELECT * FROM future', credentials.PREFLIGHT)

    def test_failed_owner_auth_or_default_acl_never_creates_preflight_authority(self):
        credentials.prepare_migration_credentials(self.release)
        for proof in ({'authentication_failed': True}, {'owner_verified': False, 'runtime_default_grants_verified': True},
                      {'owner_verified': True, 'runtime_default_grants_verified': False}):
            self.process.return_value.stdout = json.dumps(proof).encode()
            with self.subTest(proof=proof), self.assertRaisesRegex(ValueError, 'owner_or_default_grants_required'):
                credentials.preflight_migration_credentials(self.release)
        self.assertNotIn('migration_identity_preflight', self.record)
        with self.assertRaisesRegex(ValueError, 'preflight_required'):
            credentials.migration_environment(self.release)

    def test_stopped_original_recovery_requires_original_success_and_never_executes_old_app(self):
        credentials.prepare_migration_credentials(self.release)
        self.record['live']['backend']['State']['Running'] = False
        with self.assertRaisesRegex(ValueError, 'preflight_required'):
            credentials.preflight_migration_credentials(self.release)
        self.process.assert_not_called()
        self.record['live']['backend']['State']['Running'] = True
        credentials.preflight_migration_credentials(self.release)
        self.record['live']['backend']['State']['Running'] = False
        self.process.reset_mock()
        credentials.preflight_migration_credentials(self.release)
        self.process.assert_not_called()

    def test_actual_probe_program_keeps_driver_failure_details_private(self):
        driver = Mock()
        driver.connect.side_effect = RuntimeError('synthetic-secret-in-error')
        output = io.StringIO()
        source = json.dumps({**self.values, 'POSTGRES_HOST': '172.20.0.4', 'POSTGRES_PORT': '5432'}).encode()
        with patch.dict('sys.modules', {'psycopg2': driver}), patch('sys.stdin', SimpleNamespace(buffer=io.BytesIO(source))), \
                redirect_stdout(output):
            exec(compile(credentials.PREFLIGHT, '<preflight>', 'exec'), {})  # noqa: S102 - fixed reviewed probe
        self.assertEqual(json.loads(output.getvalue()), {'authentication_failed': True})
        driver.connect.assert_called_once()

    def test_actual_probe_program_requires_owner_and_runtime_default_grants(self):
        source = json.dumps({**self.values, 'POSTGRES_HOST': '172.20.0.4', 'POSTGRES_PORT': '5432',
                             'runtime_user': 'runtime'}).encode()
        driver = MagicMock()
        connection = driver.connect.return_value
        cursor = connection.cursor.return_value.__enter__.return_value = Mock()
        cursor.fetchone.side_effect = [(True,), (True, True)]
        output = io.StringIO()
        with patch.dict('sys.modules', {'psycopg2': driver}), \
                patch('sys.stdin', SimpleNamespace(buffer=io.BytesIO(source))), redirect_stdout(output):
            exec(compile(credentials.PREFLIGHT, '<preflight>', 'exec'), {})  # noqa: S102 - fixed reviewed probe
        self.assertEqual(json.loads(output.getvalue()), {'owner_verified': True, 'runtime_default_grants_verified': True})
        self.assertEqual(cursor.execute.call_count, 2)
        self.assertEqual(cursor.execute.call_args.args[1], ('runtime',))
        self.assertEqual(driver.connect.call_args.kwargs['password'], self.values['POSTGRES_PASSWORD'])
        self.assertEqual(driver.connect.call_args.kwargs['connect_timeout'], 5)
        connection.close.assert_called_once()


class RuntimeAuthority(unittest.TestCase):
    def test_initial_credentials_and_preflight_are_checked_before_build_or_worker_pause(self):
        release = release_fixture()
        release.rows = Mock(return_value=list(release.record['live'].values()))
        release.directory = Path(tempfile.mkdtemp())
        self.addCleanup(release.directory.rmdir)
        release.schema = Mock(return_value='0129_travel_tracker')
        order = []
        release.verify_migration_identity = lambda: order.append('preflight')
        release.candidate_images = lambda: order.append('build') or {}
        release.stage = Mock(return_value={})
        release.transition = Mock()
        with patch('release_companies_retained_update.prepare_migration_credentials', side_effect=lambda _: order.append('credentials')), \
                patch('release_companies_retained_update.command', return_value=str(100 * 1024 ** 3)), \
                patch('release_companies_retained_update.shutil.disk_usage', return_value=SimpleNamespace(free=100 * 1024 ** 3)), \
                patch.object(Path, 'read_text', return_value='Filename Type Size Used Priority\n'):
            release.run()
        self.assertEqual(order, ['credentials', 'preflight', 'build'])

    def test_request_and_inherited_dsns_cannot_override_selected_migration_authority(self):
        release = release_fixture()
        selected = {'POSTGRES_HOST': '172.20.0.4', 'POSTGRES_PORT': '5432', 'POSTGRES_DB': 'app',
                    'POSTGRES_USER': 'migrator', 'POSTGRES_PASSWORD': 'synthetic-migration'}
        alternate = {'DATABASE_URL': 'wrong', 'SQLALCHEMY_DATABASE_URI': 'wrong', 'POSTGRES_DSN': 'wrong'}
        release.record['live']['backend']['Config']['Env'].extend(key + '=' + value for key, value in alternate.items())
        request = {'image_id': 'candidate', 'environment': {**{key: 'attacker' for key in selected}, **alternate},
                   'arguments': ('python', 'reviewed.py')}
        with patch('release_companies_runtime.migration_environment', return_value=selected), \
                patch('release_companies_runtime.clone_payload', return_value={'HostConfig': {}}) as clone:
            helper_payload(release, request)
        values = clone.call_args.kwargs['environment']
        self.assertEqual({key: values[key] for key in selected}, selected)
        self.assertFalse(set(alternate) & set(values))

    def test_helper_capsule_omits_secrets_and_rejects_actual_configuration_drift(self):
        row = container('helper-id', 'migrator', 'synthetic-hidden')
        binding = helper_binding(row)
        self.assertEqual(set(binding), {'Id', 'Image', 'configuration_sha256'})
        self.assertNotIn('synthetic-hidden', json.dumps(binding))
        with patch('release_companies_runtime.inspect', return_value=row):
            self.assertEqual(bound_migration_helper(binding), row)
            row['Config']['Env'].append('POSTGRES_DB=other')
            with self.assertRaisesRegex(ValueError, 'helper_configuration_changed'):
                bound_migration_helper(binding)

    def test_preflight_failure_blocks_transition_and_recovery_before_any_stop(self):
        for action in ('transition', 'recover'):
            release = release_fixture()
            release.verify_migration_identity.side_effect = ValueError('preflight_rejected')
            release.stop, release.fence_candidate, release.migrate = Mock(), Mock(), Mock()
            with self.subTest(action=action), self.assertRaisesRegex(ValueError, 'preflight_rejected'):
                getattr(release, action)(*([release.record['candidates']] if action == 'transition' else []))
            release.stop.assert_not_called()
            release.fence_candidate.assert_not_called()
            release.migrate.assert_not_called()


if __name__ == '__main__':
    unittest.main()
