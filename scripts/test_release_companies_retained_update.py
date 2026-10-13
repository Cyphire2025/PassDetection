"""No Docker needed: additive admission, fencing, bounds and forward resume."""
from __future__ import annotations

import copy
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from release_companies_policy import (
    forbidden_additive_paths,
    validate_scheduler,
    validate_task_change,
)
from release_companies_retained_update import CompaniesRetainedUpdate
from release_companies_runtime import (
    database_environment,
    helper_payload,
    run_migration_helper,
)
from release_companies_traveller_contract import CHAIN, SOURCE, TARGET, source_contract
from release_retained_update import (
    ACTIVE,
    RetainedUpdate,
    runtime_environment,
    select_live,
)
from test_release_retained_update import NEXT, SHA, live_rows

ROOT = Path(__file__).resolve().parents[1]


def release_fixture():
    release = object.__new__(CompaniesRetainedUpdate)
    live = select_live(live_rows())
    for row in live.values():
        row['State'].update(ExitCode=0, OOMKilled=False)
        row['HostConfig'] = {'Memory': 1024 ** 3}
    candidates = {name: {**copy.deepcopy(live[name]), 'Id': 'candidate-' + name} for name in ACTIVE}
    release.record = {'live': live, 'candidates': candidates, 'previous_revision': SHA,
                      'additive_release': True, 'project': 'retained-test',
                      'image_ids': {'backend': 'sha256:' + 'a' * 64, 'frontend': 'sha256:' + 'b' * 64}}
    release.revision, release.mode, release.project = NEXT, 'full', 'retained-test'
    release.source, release.directory, release.artifact = ROOT, ROOT.parent, ROOT / 'artifact.json'
    release.event = lambda phase, **values: release.record.update(phase=phase, **values)
    release.current_main = Mock()
    release.compatibility = Mock()
    release.retention = Mock()
    release.proof = Mock()
    release.signed_images = Mock(return_value=release.record['image_ids'])
    return release


class AdditiveContracts(unittest.TestCase):
    def test_signed_images_must_match_exact_source_contract_and_resume_identity(self):
        release = release_fixture()
        del release.signed_images
        images = release.record['image_ids']
        manifest = {'schema': TARGET, 'deployment': source_contract(ROOT),
                    'images': {name: {'local_image_id': value} for name, value in images.items()}}
        with patch('release_companies_retained_update.verify_manifest', return_value=manifest):
            self.assertEqual(release.signed_images(), images)
            manifest['deployment']['migrations'][0]['sha256'] = '0' * 64
            with self.assertRaisesRegex(ValueError, 'Signed deployment contract'):
                release.signed_images()
            manifest['deployment'] = source_contract(ROOT)
            manifest['images']['backend']['local_image_id'] = 'sha256:' + 'c' * 64
            with self.assertRaisesRegex(ValueError, 'resume_image_binding_changed'):
                release.signed_images()

    def test_fast_cannot_select_additive_lane(self):
        release = release_fixture()
        release.mode = 'fast'
        release.rows = Mock(return_value=live_rows())
        with self.assertRaisesRegex(ValueError, 'requires_full'):
            release.run()
        release.compatibility.assert_not_called()

    def test_only_reviewed_persistent_paths_are_admitted(self):
        rejected = ['backend/alembic/versions/0129_travel_tracker.py',
                    'backend/app/core/config/settings.py', 'docker-compose.prod.yml',
                    'backend/app/infrastructure/storage/repository.py', 'nginx/nginx.conf']
        allowed = [f'backend/alembic/versions/{revision}.py' for revision in CHAIN]
        self.assertEqual(forbidden_additive_paths(rejected + allowed), rejected)

    def test_actual_scheduler_is_additive_and_old_schedule_change_rejected(self):
        path = 'backend/app/infrastructure/processing/celery_app.py'
        new = (ROOT / path).read_text()
        additions = ('"app.infrastructure.travellers.', '"reconcile-traveller-history":',
                     '"copy-retained-traveller-assets":', '"withdraw-retained-traveller-assets":',
                     '"review-traveller-document-impact":')
        old = '\n'.join(line for line in new.splitlines() if not any(value in line for value in additions))
        validate_scheduler(old, new)
        with self.assertRaises(ValueError):
            validate_scheduler(old, new.replace('schedule": 60.0', 'schedule": 61.0', 1))
        with self.assertRaises(ValueError):
            validate_scheduler(old, new.replace('"travellers.reconcile", "schedule": 5.0', '"travellers.reconcile", "schedule": 50.0'))

    def test_existing_task_contract_cannot_change(self):
        old = '@app.task(name="old.task")\ndef old_task(value): pass'
        with self.assertRaisesRegex(ValueError, 'existing_queued'):
            validate_task_change('backend/app/tasks.py', old, old.replace('(value)', '(value, extra)'))
        with self.assertRaisesRegex(ValueError, 'unreviewed_new'):
            validate_task_change('backend/app/tasks.py', '', old)
        validate_task_change('backend/app/infrastructure/travellers/tasks.py', '', old)

    def test_target_environment_changes_only_schema_and_revision(self):
        row = select_live(live_rows())['backend']
        values = runtime_environment(row, NEXT, schema=TARGET)
        self.assertEqual(values['PRIVATE_SETTING'], 'retained')
        self.assertEqual(values['APP_REVISION'], NEXT)
        self.assertEqual(values['EXPECTED_DATABASE_SCHEMA_REVISION'], TARGET)

    def test_database_uses_exact_inspected_network_and_admin_credentials(self):
        backend = {'NetworkSettings': {'Networks': {'db-net': {}, 'private': {}}}}
        db = {'NetworkSettings': {'Networks': {'db-net': {'IPAddress': '172.20.0.4'}}},
              'Config': {'Env': ['POSTGRES_USER=owner', 'POSTGRES_DB=app', 'POSTGRES_PASSWORD=synthetic-only']}}
        values = database_environment(backend, db)
        self.assertEqual(values['POSTGRES_HOST'], '172.20.0.4')
        self.assertEqual(values['POSTGRES_USER'], 'owner')
        db['NetworkSettings']['Networks']['private'] = {'IPAddress': '172.21.0.4'}
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            database_environment(backend, db)

    def test_helper_payload_is_gated_bounded_and_uses_reviewed_script(self):
        release = release_fixture()
        request = {'image_id': 'sha256:' + 'f' * 64, 'environment': {'MCP_RELEASE_PROOF_SHA256': 'e' * 64},
                   'arguments': ('python', 'scripts/release_companies_traveller_upgrade.py', '--contract-json', '{}')}
        with patch('release_companies_runtime.database_environment', return_value={'POSTGRES_HOST': '172.20.0.4'}), \
             patch('release_companies_runtime.bound_original', side_effect=lambda row: row), \
             patch('release_companies_runtime.clone_payload', return_value={'HostConfig': {}}):
            payload, gate = helper_payload(release, request)
        self.assertEqual(payload['HostConfig']['Memory'], 1024 ** 3)
        self.assertEqual(payload['HostConfig']['MemorySwap'], 1024 ** 3)
        self.assertEqual(payload['HostConfig']['PidsLimit'], 256)
        self.assertEqual(payload['HostConfig']['RestartPolicy']['Name'], 'no')
        self.assertEqual(payload['Cmd'][:3], ['python', '-B', '-c'])
        self.assertIn(gate, payload['Cmd'])
        self.assertIn('scripts/release_companies_traveller_upgrade.py', payload['Cmd'])
        self.assertEqual(payload['Cmd'][5:7], ['python', '-B'])

    def test_gate_never_opens_when_cgroup_admission_fails(self):
        release = release_fixture()
        release.verify_fence = Mock()
        release.rows = Mock(return_value=[])
        release.client = Mock()
        release.client.request.return_value = {'Id': 'h' * 64}
        release.client.inspect.return_value = {'Id': 'h' * 64}
        with patch('release_companies_runtime.helper_payload', return_value=({}, '/tmp/gate')), \
             patch('release_companies_runtime.command', return_value=str(8 * 1024 ** 3)) as run, \
             patch('release_companies_runtime.admit_builder'), \
             patch('release_companies_runtime.capture', side_effect=ValueError('cgroup_failed')), \
             self.assertRaisesRegex(ValueError, 'cgroup_failed'):
            run_migration_helper(release, {'proof': {}})
        self.assertEqual(run.call_count, 1)  # host capacity only, no gate or wait
        release.client.graceful_stop.assert_called_once()

    def test_transition_failure_never_restarts_original_writers_at_any_revision(self):
        for schema in (SOURCE, *CHAIN):
            release = release_fixture()
            release.schema = Mock(return_value=schema)
            release.stop, release.start, release.recover = Mock(), Mock(), Mock()
            release.fence_candidate = Mock()
            release.migrate = Mock(side_effect=ValueError('injected_failure'))
            with self.subTest(schema=schema), patch('release_companies_retained_update.bound_original', side_effect=lambda row: row), \
                 patch('release_companies_retained_update.require_idle'), \
                 self.assertRaisesRegex(ValueError, 'injected_failure'):
                release.transition(release.record['candidates'])
            release.start.assert_not_called()
            release.recover.assert_not_called()
            self.assertEqual(release.record['phase'], 'forward-recovery-required')

    def test_forward_resume_fences_both_generations_before_migration_and_activation(self):
        release = release_fixture()
        order = []
        release.fence_candidate = lambda row: order.append(('candidate-stop', row['Id']))
        release.stop = lambda row: order.append(('original-stop', row['Id']))
        release.migrate = lambda: order.append(('migrate', ''))
        release.activate_candidates = lambda: order.append(('activate', ''))
        release.start = Mock()
        with patch('release_companies_retained_update.bound_original', side_effect=lambda row: row):
            release.recover()
        self.assertEqual(len(order), 2 * len(ACTIVE) + 2)
        self.assertEqual(order[-2:], [('migrate', ''), ('activate', '')])
        release.start.assert_not_called()

    def test_running_helper_blocks_resume_without_stopping_it(self):
        release = release_fixture()
        release.record['migration_helpers'] = [{'Id': 'helper', 'State': {'Running': True}}]
        release.stop = Mock()
        release.fence_candidate = Mock()
        with patch('release_companies_retained_update.bound_original', side_effect=lambda row: row), \
             self.assertRaisesRegex(ValueError, 'helper_still_running'):
            release.recover()
        release.stop.assert_not_called()
        release.fence_candidate.assert_not_called()

    def test_resume_without_original_backup_fails_after_partial_upgrade(self):
        release = release_fixture()
        release.verify_fence = Mock()
        release.database_release = Mock()
        release.schema = Mock(return_value=CHAIN[0])
        with self.assertRaisesRegex(ValueError, 'original_source_backup_required'):
            release.migrate()
        release.database_release.return_value.backup.assert_not_called()

    def test_target_commit_without_final_validation_cannot_skip_helper(self):
        release = release_fixture()
        backup = {'filename': 'original-proof', 'sha256': 'b' * 64}
        release.record['database_backup'] = backup
        release.verify_fence = Mock()
        release.schema = Mock(return_value=TARGET)
        database = Mock()
        request = {'already_at_target': True, 'image_id': release.record['image_ids']['backend'],
                   'environment': {'MCP_RELEASE_PROOF_SHA256': 'd' * 64}}
        database.migration_request.return_value = request
        release.database_release = Mock(return_value=database)
        release.record['source_preservation_baseline'] = {
            'status': 'baseline_captured', 'source_schema': SOURCE, 'target_schema': TARGET,
            'preservation_sha256': 'e' * 64, 'release_proof_sha256': 'd' * 64,
            'backup_sha256': backup['sha256'], 'automatic_downgrade': False,
        }
        release.record['migration_helpers'] = [{'Id': 'validated-helper'}]
        result = {'status': 'already_at_target', 'source_schema': SOURCE, 'target_schema': TARGET,
                  'release_proof_sha256': 'd' * 64,
                  'preservation_sha256': 'e' * 64, 'new_tables_empty': True,
                  'runtime_grants_verified': True, 'automatic_downgrade': False}
        with patch('release_companies_retained_update.run_migration_helper', return_value=result) as helper:
            release.migrate()
        database.backup.assert_not_called()
        database.migration_request.assert_called_once_with(backup)
        self.assertGreater(database.verify_target.call_count, 0)
        helper.assert_called_once()
        self.assertEqual(request['environment']['MCP_RELEASE_BASELINE_SHA256'], 'e' * 64)
        self.assertEqual(release.record['database_validation']['helper_id'], 'validated-helper')

    def test_target_without_original_baseline_fails_closed_before_revalidation(self):
        release = release_fixture()
        release.schema = Mock(return_value=TARGET)
        request = {'already_at_target': True, 'environment': {'MCP_RELEASE_PROOF_SHA256': 'd' * 64}}
        with patch('release_companies_retained_update.run_migration_helper') as helper, \
             self.assertRaisesRegex(ValueError, 'original_preservation_baseline_required'):
            release.original_baseline(request, {'sha256': 'b' * 64})
        helper.assert_not_called()

    def test_original_baseline_is_captured_once_and_bound_to_backup_and_proof(self):
        release = release_fixture()
        release.schema = Mock(return_value=SOURCE)
        request = {'arguments': ('python', 'reviewed-helper.py'),
                   'environment': {'MCP_RELEASE_PROOF_SHA256': 'd' * 64}}
        result = {'status': 'baseline_captured', 'source_schema': SOURCE, 'target_schema': TARGET,
                  'preservation_sha256': 'e' * 64, 'release_proof_sha256': 'd' * 64,
                  'automatic_downgrade': False}
        with patch('release_companies_retained_update.run_migration_helper', return_value=result) as helper:
            self.assertEqual(release.original_baseline(request, {'sha256': 'b' * 64}), 'e' * 64)
            self.assertEqual(helper.call_args.args[1]['arguments'][-1], '--capture-baseline')
            release.schema.return_value = CHAIN[1]
            self.assertEqual(release.original_baseline(request, {'sha256': 'b' * 64}), 'e' * 64)
            helper.assert_called_once()
            with self.assertRaisesRegex(ValueError, 'baseline_binding_changed'):
                release.original_baseline(request, {'sha256': 'c' * 64})

    def test_validated_receipt_can_resume_after_target_app_writes(self):
        release = release_fixture()
        release.original_baseline = Mock(return_value='e' * 64)
        backup = {'sha256': 'b' * 64}
        request = {'already_at_target': True, 'image_id': release.record['image_ids']['backend'],
                   'environment': {'MCP_RELEASE_PROOF_SHA256': 'd' * 64}}
        helper = {'Id': 'validated-helper', 'Image': request['image_id'],
                  'State': {'Running': False, 'ExitCode': 0, 'OOMKilled': False}, 'RestartCount': 0}
        release.record['migration_helpers'] = [helper]
        release.record['database_validation'] = {
            'backup_sha256': backup['sha256'], 'baseline_sha256': 'e' * 64,
            'release_proof_sha256': 'd' * 64, 'image_id': request['image_id'],
            'target_schema': TARGET, 'helper_id': helper['Id'],
        }
        with patch('release_companies_retained_update.bound_original', return_value=helper):
            self.assertTrue(release.has_verified_migration(request, backup))
            helper['State']['OOMKilled'] = True
            with self.assertRaisesRegex(ValueError, 'validated_migration_helper_changed'):
                release.has_verified_migration(request, backup)

    def test_failed_final_validation_creates_no_completed_migration_receipt(self):
        release = release_fixture()
        release.verify_fence = Mock()
        release.original_baseline = Mock(return_value='e' * 64)
        release.record['database_backup'] = {'sha256': 'b' * 64}
        database = Mock()
        database.migration_request.return_value = {
            'already_at_target': True, 'image_id': release.record['image_ids']['backend'],
            'environment': {'MCP_RELEASE_PROOF_SHA256': 'd' * 64},
        }
        release.database_release = Mock(return_value=database)
        with patch('release_companies_retained_update.run_migration_helper', side_effect=ValueError('final_validation_failed')), \
             self.assertRaisesRegex(ValueError, 'final_validation_failed'):
            release.migrate()
        self.assertNotIn('database_validation', release.record)
        database.verify_target.assert_not_called()

    def test_no_candidate_starts_before_verified_target_schema(self):
        release = release_fixture()
        release.schema = Mock(return_value=CHAIN[1])
        release.start = Mock()
        with self.assertRaisesRegex(ValueError, 'target_schema_required'):
            release.activate_candidates()
        release.start.assert_not_called()

    def test_target_schema_full_release_preserves_existing_same_schema_guards(self):
        release = release_fixture()
        rows = live_rows()
        for row in rows:
            row['Config']['Env'] = [value.replace(SOURCE, TARGET) for value in row['Config']['Env']]
        release.rows = Mock(return_value=rows)
        with patch.object(RetainedUpdate, 'run') as same_schema:
            release.run()
        same_schema.assert_called_once()
        self.assertFalse(release.additive)

    def test_target_schema_fast_release_keeps_same_schema_compatibility(self):
        release = release_fixture()
        release.mode = 'fast'
        rows = live_rows()
        for row in rows:
            row['Config']['Env'] = [value.replace(SOURCE, TARGET) for value in row['Config']['Env']]
        release.rows = Mock(return_value=rows)
        with patch.object(RetainedUpdate, 'run') as same_schema:
            release.run()
        same_schema.assert_called_once()
        self.assertFalse(release.additive)


if __name__ == '__main__':
    unittest.main()
