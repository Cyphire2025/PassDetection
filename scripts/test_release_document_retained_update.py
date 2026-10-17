"""Explicit mode admission, immutable RAM evidence and fenced forward recovery."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import release_document_resources as resources
from release_document_distribution_contract import SOURCE, TARGET
from release_document_retained_update import DocumentRetainedUpdate
from release_retained_update import release_for_source
from test_mcp_direct_containers import original as app_original
from test_release_companies_retained_update import release_fixture as companies_fixture


def fixture():
    release = companies_fixture()
    release.__class__ = DocumentRetainedUpdate
    release.verify_resource_qualification = Mock()
    release.assert_writer_fence = Mock()
    release.record['database_validation'] = {'target_schema': TARGET}
    release.record['persistent'] = {}
    for row in release.record['live'].values():
        row['Config']['Env'] = [f'EXPECTED_DATABASE_SCHEMA_REVISION={SOURCE}' if value.startswith('EXPECTED_DATABASE_SCHEMA_REVISION=')
                                else value for value in row['Config']['Env']]
    return release


def redis_original():
    row = app_original('worker')
    row['Config']['Labels']['com.docker.compose.service'] = 'redis-broker'
    row['Config']['Cmd'] = ['redis-server', '--requirepass', 'synthetic', '--maxmemory', '512mb',
                            '--maxmemory-policy', 'noeviction', '--appendonly', 'yes', '--appendfsync', 'everysec']
    row['HostConfig'].update(Memory=1152 * resources.MIB, MemorySwap=1152 * resources.MIB, VolumesFrom=None)
    row['Mounts'] = [{'Type': 'volume', 'Name': 'retained-data', 'Source': '/var/lib/docker/volumes/retained-data/_data',
                      'Destination': '/data', 'RW': True, 'Driver': 'local', 'Mode': 'rw', 'Propagation': ''}]
    row['HostConfig']['Binds'] = ['retained-data:/data:rw']
    for value in row['NetworkSettings']['Networks'].values():
        value['Aliases'] = ['redis-broker', row['Id'][:12], row['Name'].lstrip('/')]
    return row


class DocumentRelease(unittest.TestCase):
    @patch('release_retained_update.load_release_manifest', return_value={'deployment_kind': 'document_distribution_updates_v1'})
    def test_factory_requires_explicit_full_or_operator_fast_mode(self, _manifest):
        source = Path(__file__).resolve().parents[1]
        with patch('release_document_retained_update.RetainedUpdate.__init__') as constructor:
            self.assertIsInstance(release_for_source(source, 'a' * 40, 'full', source / 'artifact'), DocumentRetainedUpdate)
            constructor.assert_called_once()
        with patch('release_document_retained_update.RetainedUpdate.__init__') as constructor:
            self.assertIsInstance(release_for_source(source, 'a' * 40, 'fast', None), DocumentRetainedUpdate)
            constructor.assert_called_once()
        for mode, artifact in [('fast', source / 'artifact'), ('full', None)]:
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, 'explicit_mode_binding'):
                release_for_source(source, 'a' * 40, mode, artifact)

    def test_resource_failure_never_starts_target_or_old_writers(self):
        release = fixture()
        release.stop, release.migrate, release.activate_candidates, release.hold_candidates = Mock(), Mock(), Mock(), Mock()
        with patch('release_document_retained_update.bound_original', side_effect=lambda row: row), \
             patch('release_document_retained_update.wait_for_idle'), \
             patch('release_document_retained_update.resources.preflight_fenced'), \
             patch('release_document_retained_update.resources.apply', side_effect=ValueError('resource_blocked')), \
             self.assertRaisesRegex(ValueError, 'resource_blocked'):
            release.transition(release.record['candidates'])
        release.migrate.assert_called_once()
        release.activate_candidates.assert_not_called()
        release.hold_candidates.assert_called_once()

    def test_cutover_order_is_preflight_migration_resources_activation(self):
        release = fixture()
        sequence = []
        release.stop = Mock()
        release.migrate = lambda: sequence.append('migrate')
        release.activate_candidates = lambda: sequence.append('activate')
        with patch('release_document_retained_update.bound_original', side_effect=lambda row: row), \
             patch('release_document_retained_update.wait_for_idle'), \
             patch('release_document_retained_update.resources.preflight_fenced', side_effect=lambda _: sequence.append('preflight')), \
             patch('release_document_retained_update.resources.apply', side_effect=lambda _: sequence.append('resources')):
            release.transition(release.record['candidates'])
        self.assertEqual(sequence, ['preflight', 'migrate', 'resources', 'activate'])

    def test_fenced_inventory_failure_prevents_migration(self):
        release = fixture()
        release.stop, release.migrate, release.activate_candidates, release.hold_candidates = Mock(), Mock(), Mock(), Mock()
        with patch('release_document_retained_update.bound_original', side_effect=lambda row: row), \
             patch('release_document_retained_update.wait_for_idle'), \
             patch('release_document_retained_update.resources.preflight_fenced', side_effect=ValueError('key_inventory')), \
             patch('release_document_retained_update.resources.apply') as apply, \
             self.assertRaisesRegex(ValueError, 'key_inventory'):
            release.transition(release.record['candidates'])
        release.migrate.assert_not_called()
        apply.assert_not_called()
        release.activate_candidates.assert_not_called()
        release.hold_candidates.assert_called_once()

    def test_unverified_resume_rechecks_only_before_target_schema(self):
        for schema in (SOURCE, TARGET):
            with self.subTest(schema=schema):
                release = fixture()
                release.record.pop('database_validation')
                release.stop, release.fence_candidate = Mock(), Mock()
                release.migrate, release.activate_candidates = Mock(), Mock()
                release.schema = Mock(return_value=schema)
                with patch('release_document_retained_update.bound_original', side_effect=lambda row: row), \
                     patch('release_document_retained_update.resources.preflight_fenced') as preflight, \
                     patch('release_document_retained_update.resources.apply'):
                    release.recover()
                self.assertEqual(preflight.call_count, 1 if schema == SOURCE else 0)

    def test_resume_finishes_resources_before_full_infrastructure_fence(self):
        release = fixture()
        release.stop, release.fence_candidate = Mock(), Mock()
        sequence = []
        release.migrate = lambda: sequence.append('verify_migration')
        release.activate_candidates = lambda: sequence.append('activate')
        with patch('release_document_retained_update.bound_original', side_effect=lambda row: row), \
             patch('release_document_retained_update.resources.preflight_fenced') as preflight, \
             patch('release_document_retained_update.resources.apply', side_effect=lambda _: sequence.append('resources')):
            release.recover()
        self.assertEqual(sequence, ['resources', 'verify_migration', 'resources', 'activate'])
        preflight.assert_not_called()

    def test_missing_evidence_blocks_resume_before_any_stop(self):
        release = fixture()
        release.verify_candidate_configuration.side_effect = ValueError('resource_qualification_binding_changed')
        release.stop, release.fence_candidate = Mock(), Mock()
        with self.assertRaisesRegex(ValueError, 'resource_qualification'):
            release.recover()
        release.stop.assert_not_called()
        release.fence_candidate.assert_not_called()

    def test_migration_result_requires_null_new_columns(self):
        release = fixture()
        release.verify_fence = Mock()
        release.record['database_backup'] = {'sha256': 'backup'}
        database = Mock()
        database.migration_request.return_value = {'environment': {'MCP_RELEASE_PROOF_SHA256': 'proof'}, 'image_id': 'image'}
        release.database_release = Mock(return_value=database)
        release.has_verified_migration = Mock(return_value=False)
        release.original_baseline = Mock(return_value='baseline')
        result = {'status': 'upgraded', 'source_schema': SOURCE, 'target_schema': TARGET,
                  'release_proof_sha256': 'proof', 'preservation_sha256': 'baseline',
                  'new_tables_empty': True, 'runtime_grants_verified': True, 'automatic_downgrade': False}
        with patch('release_document_retained_update.run_migration_helper', return_value=result), \
             self.assertRaisesRegex(ValueError, 'complete_migration_validation_required'):
            release.migrate()
        database.verify_target.assert_not_called()

    def test_live_helper_blocks_recovery_without_stopping_app(self):
        release = fixture()
        release.record['migration_helpers'] = [{'Id': 'helper'}]
        release.stop, release.fence_candidate = Mock(), Mock()
        with patch('release_document_retained_update.bound_migration_helper', return_value={'State': {'Running': True}}), \
             self.assertRaisesRegex(ValueError, 'migration_helper_still_running'):
            release.recover()
        release.stop.assert_not_called()


class ResourceContracts(unittest.TestCase):
    def test_only_worker_frontend_caps_change_when_cloning(self):
        release = SimpleNamespace(client=Mock())
        release.client.request.return_value = {'Id': 'b' * 64}
        release.client.identifier.side_effect = lambda value: value
        original = app_original('worker')
        original['HostConfig'].update(Memory=384 * resources.MIB, MemorySwap=384 * resources.MIB)
        from test_mcp_direct_containers import options
        resources.create_app_candidate(release, original, options())
        payload = release.client.request.call_args.args[2]
        self.assertEqual(payload['HostConfig']['Memory'], 1024 * resources.MIB)
        self.assertEqual(payload['HostConfig']['MemorySwap'], 1024 * resources.MIB)
        self.assertEqual(original['HostConfig']['Memory'], 384 * resources.MIB)
        self.assertEqual(payload['Cmd'], original['Config']['Cmd'])

    def test_redis_clone_retains_volume_auth_image_cpu_and_service_dns(self):
        original = redis_original()
        argv = original['Config']['Cmd'].copy()
        argv[argv.index('--maxmemory') + 1] = str(384 * resources.MIB)
        release = SimpleNamespace(project='retained-next', source=Path('/opt/GlobalConnectsDashboard/tmp/mcp-direct-test/source'))
        entry = {'original': original, 'command': argv, 'memory': 896 * resources.MIB}
        payload = resources.redis_payload(release, 'redis-broker', entry)
        self.assertEqual(payload['Image'], original['Image'])
        self.assertEqual(payload['HostConfig']['Binds'], ['retained-data:/data:rw'])
        self.assertEqual(payload['HostConfig']['NanoCpus'], original['HostConfig']['NanoCpus'])
        self.assertEqual(payload['Env'], original['Config']['Env'])
        self.assertEqual(payload['HostConfig']['MemorySwap'], 896 * resources.MIB)
        for endpoint in payload['NetworkingConfig']['EndpointsConfig'].values():
            self.assertIn('redis-broker', endpoint['Aliases'])
            self.assertNotIn(original['Name'].lstrip('/'), endpoint['Aliases'])
        changed = copy.deepcopy(entry)
        changed['command'][-1] = 'no'
        with self.assertRaisesRegex(ValueError, 'unreviewed_redis'):
            resources.redis_payload(release, 'redis-broker', changed)

    def test_resource_receipt_binds_images_sources_and_exact_resume_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for filename in (resources.PROFILE, resources.OVERLAY, *resources.QUALIFIED_SOURCES):
                path = root / filename
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('synthetic')
            release = SimpleNamespace(directory=root, source=root, revision='a' * 40,
                record={'image_ids': {'backend': 'sha256:' + 'a' * 64, 'frontend': 'sha256:' + 'b' * 64},
                        'live': {name: {'Image': 'sha256:' + 'c' * 64} for name in resources.DATASETS}})
            value = {'version': 1, 'kind': 'document_distribution_resources_v1', 'qualified': True,
                     'revision': release.revision, 'image_ids': {**release.record['image_ids'],
                         **{name: row['Image'] for name, row in release.record['live'].items()}},
                     'profile_sha256': resources.sha256(root / resources.PROFILE),
                     'overlay_sha256': resources.sha256(root / resources.OVERLAY),
                     'source_sha256': resources.qualified_source_hashes(root),
                     'limits_mib': {name: pair[1] for name, pair in resources.LIMITS.items()},
                     'redis_maxmemory_mib': resources.DATASETS, 'host_reserve_mib': 2048,
                     'provider_calls': 0, 'checks': resources.CHECKS, 'evidence_sha256': {'synthetic': 'a' * 64}}
            path = root / resources.RECEIPT
            path.write_text(json.dumps(value))
            path.chmod(0o600)
            release.record['resource_qualification'] = resources.qualification(release)
            self.assertEqual(resources.qualification(release), release.record['resource_qualification'])
            for key, substitute in [('version', True), ('qualified', 1), ('provider_calls', False),
                                    ('checks', {**resources.CHECKS, 'oom_free': 1})]:
                altered = {**value, key: substitute}
                path.write_text(json.dumps(altered))
                with self.assertRaisesRegex(ValueError, 'binding_changed'):
                    resources.qualification(release)
            path.write_text(json.dumps(value, indent=2))
            with self.assertRaisesRegex(ValueError, 'changed_on_resume'):
                resources.qualification(release)
            release.record.pop('resource_qualification')
            (root / resources.QUALIFIED_SOURCES[0]).write_text('changed')
            with self.assertRaisesRegex(ValueError, 'binding_changed'):
                resources.qualification(release)

    def test_missing_receipt_does_not_mean_qualified(self):
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(ValueError, 'qualification_required'):
            resources.qualification(SimpleNamespace(directory=Path(directory)))

    def test_fresh_preparation_runs_exact_image_probe_before_mutations(self):
        with tempfile.TemporaryDirectory() as directory:
            release = SimpleNamespace(directory=Path(directory), source=Path(directory), revision='a' * 40,
                record={'image_ids': {'backend': 'backend-id', 'frontend': 'frontend-id'},
                        'live': {name: {'Image': name + '-id'} for name in ('redis-broker', 'redis-cache', 'db')}})
            with patch.object(resources, 'command') as execute, patch.object(resources, 'qualification') as verify:
                resources.ensure_qualification(release)
                args = execute.call_args.args
                self.assertEqual(args[args.index('--backend-image') + 1], 'backend-id')
                self.assertEqual(args[args.index('--postgres-image') + 1], 'db-id')
                self.assertEqual(args[args.index('--revision') + 1], release.revision)
                verify.assert_called_once_with(release)
            release.record['candidates'] = {}
            with patch.object(resources, 'command') as execute, self.assertRaisesRegex(ValueError, 'missing_on_resume'):
                resources.ensure_qualification(release)
            execute.assert_not_called()

    def test_failed_probe_never_emits_a_qualified_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            release = SimpleNamespace(directory=Path(directory), source=Path(directory), revision='a' * 40,
                record={'image_ids': {'backend': 'backend-id', 'frontend': 'frontend-id'},
                        'live': {name: {'Image': name + '-id'} for name in ('redis-broker', 'redis-cache', 'db')}})
            with patch.object(resources, 'command', side_effect=ValueError('probe_failed')), \
                 patch.object(resources, 'qualification') as verify, self.assertRaisesRegex(ValueError, 'probe_failed'):
                resources.ensure_qualification(release)
            verify.assert_not_called()

    def test_resource_transition_requires_verified_migration(self):
        release = SimpleNamespace(record={'resource_qualification': {'bound': True}})
        with patch.object(resources, 'qualification', return_value={'bound': True}), \
             self.assertRaisesRegex(ValueError, 'verified_database_migration_required'):
            resources.apply(release)

    def test_retained_redis_timeout_never_force_kills(self):
        release = SimpleNamespace(directory=Path('.'), revision='a' * 40, client=Mock())
        release.client.inspect.return_value = {'State': {'Running': True}}
        adapter = resources.RetainedRedis(release)
        with patch.object(resources.time, 'monotonic', side_effect=[0, 181]), \
             self.assertRaisesRegex(ValueError, 'no_force_stop'):
            adapter.run('docker', 'stop', '--time', '180', 'a' * 64)
        release.client.request.assert_called_once_with('POST', '/containers/' + 'a' * 64 + '/kill?signal=TERM')

    def test_orphan_binding_normalizes_only_empty_mounts(self):
        from release_document_resource_binding import verify_payload
        original = redis_original()
        command = original['Config']['Cmd'].copy()
        command[command.index('--maxmemory') + 1] = str(384 * resources.MIB)
        release = SimpleNamespace(project='retained-next', source=Path('/opt/source'))
        payload = resources.redis_payload(release, 'redis-broker',
            {'original': original, 'command': command, 'memory': 896 * resources.MIB})
        actual = {'Config': {key: value for key, value in payload.items() if key not in {'HostConfig', 'NetworkingConfig'}},
                  'HostConfig': copy.deepcopy(payload['HostConfig']),
                  'NetworkSettings': {'Networks': copy.deepcopy(payload['NetworkingConfig']['EndpointsConfig'])}}
        actual['HostConfig'].pop('Mounts')
        verify_payload(actual, payload)
        actual['HostConfig']['Memory'] += 1
        with self.assertRaisesRegex(ValueError, 'host_configuration_changed'):
            verify_payload(actual, payload)


if __name__ == '__main__':
    unittest.main()
