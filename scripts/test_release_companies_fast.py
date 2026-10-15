"""Exact Fast additive image and rehearsal evidence; never run Docker here."""
from __future__ import annotations

import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from legacy_company_contract_fixture import company_source
from release_companies_fast import (
    CHECKS,
    binding,
    read_rehearsal,
    validate_dependencies,
    verify_images,
    verify_rehearsal,
)
from release_companies_traveller_contract import SOURCE, TARGET
from release_retained_update import WORKERS, RetainedUpdate
from test_release_companies_retained_update import NEXT, ROOT, release_fixture


def fast_fixture(source: Path):
    release = release_fixture()
    release.source = source
    release.mode, release.artifact = 'fast', None
    builds = {}
    inspected = []
    for index, name in enumerate(('backend', 'frontend')):
        builds[name] = {'image_id': release.record['image_ids'][name],
                        'base_image_id': release.record['live'][name]['Image'],
                        'container_id': str(index + 1) * 64, 'exit_code': 0, 'oom_killed': False}
        config = {'Labels': {'org.opencontainers.image.revision': NEXT}, 'User': '1001:1001',
                  'WorkingDir': '/app', 'Entrypoint': []}
        if name == 'backend':
            config.update(Env=[f'APP_REVISION={NEXT}', f'EXPECTED_DATABASE_SCHEMA_REVISION={TARGET}'],
                          Cmd=['gunicorn', '--config', 'gunicorn.conf.py', 'app.main:app'])
        else:
            config.update(Env=[f'NEXT_PUBLIC_APP_REVISION={NEXT}'], Cmd=['node', 'server.js'])
            builds[name]['runtime_container_id'] = '3' * 64
        inspected.append({'Id': release.record['image_ids'][name], 'Config': config})
    release.record['fast_build'] = builds
    release.record['fast_additive_binding'] = binding(source, NEXT, release.record)
    builds['backend']['verified_api_contract_sha256'] = release.record['fast_additive_binding']['backend_api_contract_sha256']
    return release, inspected


def receipt_for(release):
    return {'version': 1, 'status': 'passed', 'source_revision': NEXT,
            'backend_image_id': release.record['image_ids']['backend'],
            'source_contract_sha256': release.record['fast_additive_binding']['source_contract_sha256'],
            'source_schema': SOURCE, 'target_schema': TARGET, 'full_ci_qualified': False,
            'owned_resources_removed': True, 'fixture_person_count': 700, 'contact_concurrency_tests': 2,
            'draft_ddl_rollback_verified': True, 'directory_ddl_rollback_verified': True, 'lookup_ddl_rollback_verified': True,
            'split_migration_role_verified': True,
            'checks': dict.fromkeys(CHECKS, True)}


class FastAdditiveProofTests(unittest.TestCase):
    def setUp(self):
        self.source = self.enterContext(company_source())
        contract = self.source / 'backend/contracts/api.openapi.json'
        contract.parent.mkdir(parents=True)
        shutil.copyfile(ROOT / 'backend/contracts/api.openapi.json', contract)

    def test_dependency_change_is_rejected_before_build(self):
        with patch('release_companies_fast.command', return_value='backend/requirements.lock'), \
                self.assertRaisesRegex(ValueError, 'dependencies_must_be_unchanged'):
            validate_dependencies(ROOT, 'a' * 40, NEXT)
        with patch('release_companies_fast.command', return_value=''):
            validate_dependencies(ROOT, 'a' * 40, NEXT)

    def test_exact_images_bases_api_and_stopped_builders_are_required(self):
        release, inspected = fast_fixture(self.source)
        def command(*arguments):
            if arguments[:3] == ('docker', 'image', 'inspect'):
                return json.dumps(inspected)
            return json.dumps([{'Id': arguments[-1], 'State': {'Running': False, 'ExitCode': 0, 'OOMKilled': False}}])
        with patch('release_companies_fast.command', side_effect=command):
            self.assertEqual(verify_images(self.source, NEXT, release.record), release.record['image_ids'])
            for changes in (
                {'source_contract_sha256': 'f' * 64}, {'full_ci_qualified': True},
                {'dockerfile_native_security_changes_applied': True},
                {'base_image_ids': {'backend': 'sha256:' + 'f' * 64, 'frontend': 'sha256:' + 'b' * 64}},
            ):
                record = copy.deepcopy(release.record)
                record['fast_additive_binding'].update(changes)
                with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, 'binding_changed'):
                    verify_images(self.source, NEXT, record)
            inspected[0]['Config']['Env'][-1] = f'EXPECTED_DATABASE_SCHEMA_REVISION={SOURCE}'
            with self.assertRaisesRegex(ValueError, 'backend_proof_changed'):
                verify_images(self.source, NEXT, release.record)

    def test_running_or_failed_builder_blocks_recovery(self):
        release, inspected = fast_fixture(self.source)
        for changed in ({'Running': True}, {'ExitCode': 2}, {'OOMKilled': True}):
            state = {'Running': False, 'ExitCode': 0, 'OOMKilled': False, **changed}
            def command(*arguments, state=state):
                return json.dumps(inspected if arguments[1] == 'image' else [{'Id': arguments[-1], 'State': state}])
            with self.subTest(changed=changed), patch('release_companies_fast.command', side_effect=command), \
                    self.assertRaisesRegex(ValueError, 'successfully_stopped'):
                verify_images(self.source, NEXT, release.record)

    def test_rehearsal_requires_exact_image_source_and_all_failure_controls(self):
        release, _ = fast_fixture(self.source)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fast-migration-rehearsal.json'
            original = receipt_for(release)
            for changes in ({}, {'backend_image_id': 'sha256:' + 'f' * 64}, {'source_revision': 'f' * 40},
                            {'source_contract_sha256': 'f' * 64}, {'fixture_person_count': 699},
                            {'owned_resources_removed': False}, {'full_ci_qualified': True}, {'contact_concurrency_tests': 0},
                            {'draft_ddl_rollback_verified': False}, {'draft_ddl_rollback_verified': 1},
                            {'directory_ddl_rollback_verified': False}, {'directory_ddl_rollback_verified': 1},
                            {'split_migration_role_verified': False}, {'split_migration_role_verified': 1},
                            {'checks': {**original['checks'], 'wrong_baseline_rejected': 1}}):
                path.write_text(json.dumps({**original, **changes}))
                path.chmod(0o600)
                if not changes:
                    saved = read_rehearsal(path, release.record['fast_additive_binding'])
                    release.record['fast_migration_rehearsal'] = saved
                    verify_rehearsal(Path(directory), release.record)
                else:
                    with self.subTest(changes=changes), self.assertRaises(ValueError):
                        verify_rehearsal(Path(directory), release.record)
            path.write_text(json.dumps({**original, 'additional': 'changed after proof'}))
            with self.assertRaisesRegex(ValueError, 'receipt_changed'):
                verify_rehearsal(Path(directory), release.record)

    def test_missing_required_failure_control_cannot_authorize_live_migration(self):
        release, _ = fast_fixture(self.source)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fast-migration-rehearsal.json'
            for required in ('draft_ddl_rollback_verified', 'split_migration_role_verified'):
                proof = receipt_for(release)
                proof.pop(required)
                path.write_text(json.dumps(proof))
                path.chmod(0o600)
                with self.subTest(required=required), self.assertRaisesRegex(ValueError, 'receipt_binding_changed'):
                    read_rehearsal(path, release.record['fast_additive_binding'])

    def test_recovery_never_rebuilds_or_reruns_rehearsal(self):
        release, _ = fast_fixture(self.source)
        release.build_fast_images, release.rehearse_fast_migration = Mock(), Mock()
        with patch('release_companies_fast.verify_images', return_value=release.record['image_ids']), \
                patch('release_companies_fast.verify_rehearsal') as verify:
            release.candidate_images(recover=True)
        release.build_fast_images.assert_not_called()
        release.rehearse_fast_migration.assert_not_called()
        verify.assert_called_once_with(release.directory, release.record)

    def test_build_and_rehearsal_share_background_pause_before_workers_resume(self):
        release, _ = fast_fixture(self.source)
        live = release.record['live']
        running = {row['Id']: row for row in live.values()}
        release.record['inventory'] = dict(running)
        release.rows = lambda: list(running.values())
        release.stop = lambda row: running.pop(row['Id'])
        release.start = lambda row: running.update({row['Id']: row})
        checked = []
        def paused(stage):
            self.assertTrue(all(live[name]['Id'] not in running for name in (*WORKERS, 'email-beat')))
            self.assertIn(live['backend']['Id'], running)
            self.assertIn(live['nginx']['Id'], running)
            checked.append(stage)
        def build():
            paused('build')
            return release.record['image_ids']
        release.build_fast_images = build
        release.rehearse_fast_migration = lambda: paused('rehearsal')
        def drain(containers):
            self.assertIs(containers, live)
            self.assertNotIn(live['email-beat']['Id'], running)
            self.assertTrue(all(live[name]['Id'] in running for name in WORKERS))
            checked.append('drain')
        with patch('release_retained_update.wait_for_idle', side_effect=drain), patch('release_companies_fast.verify_images',
                                                               return_value=release.record['image_ids']):
            release.candidate_images()
        self.assertEqual(checked, ['drain', 'build', 'rehearsal'])
        self.assertEqual(set(running), set(release.record['inventory']))

    def test_cleaned_failure_resumes_workers_but_unknown_live_helper_does_not(self):
        for helper_running in (False, True):
            release, _ = fast_fixture(self.source)
            live = release.record['live']
            running = {row['Id']: row for row in live.values()}
            release.record['inventory'] = dict(running)
            release.rows = lambda running=running: list(running.values())
            release.stop = lambda row, running=running: running.pop(row['Id'])
            release.start = Mock(side_effect=lambda row, running=running: running.update({row['Id']: row}))
            release.build_fast_images = Mock(return_value=release.record['image_ids'])
            def rehearsal(helper_running=helper_running, running=running):
                if helper_running:
                    running['unknown-helper'] = {'Id': 'unknown-helper'}
                raise ValueError('rehearsal_failed')
            release.rehearse_fast_migration = rehearsal
            error = 'builder_still_running_workers_not_resumed' if helper_running else 'rehearsal_failed'
            with self.subTest(helper_running=helper_running), patch('release_retained_update.wait_for_idle'), \
                    patch('release_companies_fast.verify_images', return_value=release.record['image_ids']), \
                    self.assertRaisesRegex(ValueError, error):
                release.candidate_images()
            self.assertEqual(release.start.call_count, 0 if helper_running else len(WORKERS) + 1)

    def test_generic_fast_still_builds_inside_pause_then_resumes(self):
        release, _ = fast_fixture(self.source)
        release.stop, release.start = Mock(), Mock()
        release.record['inventory'] = {row['Id']: row for row in release.record['live'].values()}
        release.rows = Mock(return_value=list(release.record['live'].values()))
        release.build_fast_images = Mock(return_value=release.record['image_ids'])
        with patch('release_retained_update.wait_for_idle'):
            self.assertEqual(RetainedUpdate.fast_images(release), release.record['image_ids'])
        self.assertEqual(release.stop.call_count, len(WORKERS) + 1)
        self.assertEqual(release.start.call_count, len(WORKERS) + 1)

    def test_missing_rehearsal_blocks_before_live_backup_or_ddl(self):
        release, _ = fast_fixture(self.source)
        release.verify_fence, release.database_release = Mock(), Mock()
        with patch('release_companies_fast.verify_images'), \
                self.assertRaisesRegex(ValueError, 'rehearsal_required'):
            release.migrate()
        release.verify_fence.assert_not_called()
        release.database_release.assert_not_called()

    def test_full_path_never_calls_local_builder(self):
        release = release_fixture()
        release.fast_images = Mock()
        self.assertEqual(release.candidate_images(), release.record['image_ids'])
        release.signed_images.assert_called_once()
        release.fast_images.assert_not_called()


if __name__ == '__main__':
    unittest.main()
