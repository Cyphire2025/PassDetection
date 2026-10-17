"""Operator Fast builds retain exact image/schema/resource gates without Full claims."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from release_document_distribution_contract import SOURCE, TARGET
from release_document_distribution_contract import source_contract as historical_contract
from legacy_document_contract_fixture import document_source
from release_document_fast import (
    CHECKS,
    binding,
    read_rehearsal,
    validate_dependencies,
    verify_images,
    verify_rehearsal,
)
from release_retained_update import WORKERS
from test_release_document_retained_update import fixture

ROOT = Path(__file__).resolve().parents[1]


def fast_fixture():
    release = fixture()
    release.mode, release.artifact = 'fast', None
    builds, inspected = {}, []
    for index, name in enumerate(('backend', 'frontend')):
        builds[name] = {'image_id': release.record['image_ids'][name],
                       'base_image_id': release.record['live'][name]['Image'],
                       'container_id': str(index + 1) * 64, 'exit_code': 0, 'oom_killed': False}
        config = {'Labels': {'org.opencontainers.image.revision': release.revision}, 'User': '1001:1001',
                  'WorkingDir': '/app', 'Entrypoint': []}
        if name == 'backend':
            config.update(Env=[f'APP_REVISION={release.revision}', f'EXPECTED_DATABASE_SCHEMA_REVISION={TARGET}'],
                          Cmd=['gunicorn', '--config', 'gunicorn.conf.py', 'app.main:app'])
        else:
            config.update(Env=[f'NEXT_PUBLIC_APP_REVISION={release.revision}'], Cmd=['node', 'server.js'])
            builds[name]['runtime_container_id'] = '3' * 64
        inspected.append({'Id': release.record['image_ids'][name], 'Config': config})
    release.record['fast_build'] = builds
    release.record['fast_document_binding'] = binding(ROOT, release.revision, release.record)
    builds['backend']['verified_api_contract_sha256'] = release.record['fast_document_binding']['backend_api_contract_sha256']
    return release, inspected


def receipt(release):
    return {'version': 1, 'status': 'passed', 'source_revision': release.revision,
            'backend_image_id': release.record['image_ids']['backend'],
            'source_contract_sha256': release.record['fast_document_binding']['source_contract_sha256'],
            'source_schema': SOURCE, 'target_schema': TARGET, 'full_ci_qualified': False,
            'owned_resources_removed': True, 'checks': dict.fromkeys(CHECKS, True)}


class FastDocumentTests(unittest.TestCase):
    def setUp(self):
        fixture = document_source()
        source = fixture.__enter__()
        self.addCleanup(fixture.__exit__, None, None, None)
        contract_patch = patch('release_document_fast.source_contract', side_effect=lambda _: historical_contract(source))
        contract_patch.start()
        self.addCleanup(contract_patch.stop)

    def test_backend_dependency_drift_requires_separate_build(self):
        with patch('release_document_fast.command', return_value='backend/requirements.lock'), \
             self.assertRaisesRegex(ValueError, 'dependencies_must_be_unchanged'):
            validate_dependencies(ROOT, 'a' * 40, 'b' * 40)

    def test_image_schema_base_builder_and_no_full_claim_are_bound(self):
        release, inspected = fast_fixture()
        def command(*args):
            if args[:3] == ('docker', 'image', 'inspect'):
                return json.dumps(inspected)
            return json.dumps([{'Id': args[-1], 'State': {'Running': False, 'ExitCode': 0, 'OOMKilled': False}}])
        with patch('release_document_fast.command', side_effect=command):
            self.assertEqual(verify_images(ROOT, release.revision, release.record), release.record['image_ids'])
            for change in ({'full_ci_qualified': True}, {'operator_selected_vps_build': 1},
                           {'runtime_inherited_from_previous_images': False}, {'source_contract_sha256': 'f' * 64}):
                record = copy.deepcopy(release.record)
                record['fast_document_binding'].update(change)
                with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'binding_changed'):
                    verify_images(ROOT, release.revision, record)
            inspected[0]['Config']['Env'][-1] = f'EXPECTED_DATABASE_SCHEMA_REVISION={SOURCE}'
            with self.assertRaisesRegex(ValueError, 'backend_proof_changed'):
                verify_images(ROOT, release.revision, release.record)

    def test_running_or_failed_builder_cannot_be_reused(self):
        release, inspected = fast_fixture()
        for changed in ({'Running': True}, {'ExitCode': 1}, {'OOMKilled': True}):
            state = {'Running': False, 'ExitCode': 0, 'OOMKilled': False, **changed}
            def command(*args, state=state):
                return json.dumps(inspected if args[1] == 'image' else [{'Id': args[-1], 'State': state}])
            with self.subTest(changed=changed), patch('release_document_fast.command', side_effect=command), \
                 self.assertRaisesRegex(ValueError, 'successfully_stopped'):
                verify_images(ROOT, release.revision, release.record)

    def test_exact_migration_receipt_checks_are_required_and_immutable(self):
        release, _ = fast_fixture()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fast-document-migration-rehearsal.json'
            original = receipt(release)
            path.write_text(json.dumps(original))
            path.chmod(0o600)
            release.record['fast_document_migration_rehearsal'] = read_rehearsal(path, release.record['fast_document_binding'])
            verify_rehearsal(Path(directory), release.record)
            for change in ({'version': True}, {'full_ci_qualified': True}, {'owned_resources_removed': False},
                           {'backend_image_id': 'sha256:' + 'f' * 64}, {'source_schema': '0135_company_removal_history'},
                           {'checks': {**original['checks'], 'new_columns_null': 1}},
                           {'checks': {**original['checks'], 'lock_failure': False}}):
                path.write_text(json.dumps({**original, **change}))
                with self.subTest(change=change), self.assertRaises(ValueError):
                    verify_rehearsal(Path(directory), release.record)

    def test_resume_does_not_rebuild_or_rehearse(self):
        release, _ = fast_fixture()
        release.build_fast_images, release.rehearse_fast_migration = Mock(), Mock()
        with patch('release_document_fast.verify_images', return_value=release.record['image_ids']), \
             patch('release_document_fast.verify_rehearsal') as verify:
            release.candidate_images(recover=True)
        release.build_fast_images.assert_not_called()
        release.rehearse_fast_migration.assert_not_called()
        verify.assert_called_once_with(release.directory, release.record)

    def test_build_and_rehearsal_hold_background_workers_paused(self):
        release, _ = fast_fixture()
        live = release.record['live']
        running = {row['Id']: row for row in live.values()}
        release.record['inventory'] = dict(running)
        release.rows = lambda: list(running.values())
        release.stop = lambda row: running.pop(row['Id'])
        release.start = lambda row: running.update({row['Id']: row})
        stages = []
        def paused(stage):
            self.assertTrue(all(live[name]['Id'] not in running for name in (*WORKERS, 'email-beat')))
            self.assertIn(live['backend']['Id'], running)
            stages.append(stage)
        release.build_fast_images = lambda: (paused('build') or release.record['image_ids'])
        release.rehearse_fast_migration = lambda: paused('rehearse')
        with patch('release_retained_update.wait_for_idle'), \
             patch('release_document_retained_update.capture_background_source'), \
             patch('release_document_retained_update.capture_background_resume'), \
             patch('release_document_retained_update.verify_background_stopped'), \
             patch('release_document_fast.verify_images', return_value=release.record['image_ids']), \
             patch('release_document_fast.verify_rehearsal'):
            release.candidate_images()
        self.assertEqual(stages, ['build', 'rehearse'])
        self.assertEqual(set(running), set(release.record['inventory']))

    def test_unknown_running_helper_blocks_old_worker_resume(self):
        release, _ = fast_fixture()
        live = release.record['live']
        running = {row['Id']: row for row in live.values()}
        release.record['inventory'] = dict(running)
        release.rows = lambda: list(running.values())
        release.stop = lambda row: running.pop(row['Id'])
        release.start = Mock()
        release.build_fast_images = Mock(return_value=release.record['image_ids'])
        def rehearsal():
            running['helper'] = {'Id': 'helper'}
            raise ValueError('rehearsal_failed')
        release.rehearse_fast_migration = rehearsal
        with patch('release_retained_update.wait_for_idle'), \
             patch('release_document_retained_update.capture_background_source'), \
             patch('release_document_retained_update.capture_background_resume'), \
             patch('release_document_retained_update.verify_background_stopped'), \
             patch('release_document_fast.verify_images', return_value=release.record['image_ids']), \
             self.assertRaisesRegex(ValueError, 'builder_still_running_workers_not_resumed'):
            release.candidate_images()
        release.start.assert_not_called()


if __name__ == '__main__':
    unittest.main()
