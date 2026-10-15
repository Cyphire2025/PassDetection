"""Source admission with real temporary Git histories; no Docker or live data."""
from __future__ import annotations

import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import release_document_distribution_policy as policy

TASK_BEFORE = '''@celery_app.task(bind=True, name="whatsapp.process_document_broadcast", queue="whatsapp", max_retries=2, default_retry_delay=10)
def process_document_whatsapp_broadcast(self: _BoundTask, *, send_batch_id: str) -> None:
    return run(send_batch_id)
'''
TASK_ADDITION = '''
@celery_app.task(bind=True, name="whatsapp.process_document_update_broadcast", queue="whatsapp", max_retries=2, default_retry_delay=10, soft_time_limit=9 * 60, time_limit=10 * 60)
def process_document_update_broadcast(self: _BoundTask, *, batch_id: str) -> None:
    return run_update(batch_id)
'''
FACADE_IMPORTS = '''from app.infrastructure.database import (
    company_data_export_models as _company_data_export_models,
    company_directory_queue as _company_directory_queue,
    traveller_reuse_models as _traveller_reuse_models,
    traveller_returning_draft_models as _traveller_returning_draft_models,
)
'''


def field_sources(path: str) -> tuple[str, str]:
    name, declarations = policy.FIELD_ADDITIONS[path]
    imports = FACADE_IMPORTS if path.endswith('/models.py') else ''
    old = imports + f'class {name}:\n    existing: str = "unchanged café 日本"\n'
    return old, old + ''.join('    ' + declaration + '\n' for declaration in declarations)


def profile_sources() -> tuple[dict, dict]:
    original = {'qualification_status': 'qualified', 'qualification_scope': 'previous_evidence',
                'host_reserve_mib': 2048, 'worker_children_each': 1,
                'memory_limits_mib': {name: values[0] for name, values in policy.MEMORY_CHANGES.items()},
                'evidence': {'existing': 'existing.json'},
                'limitations': ['Do not delete data', policy.PREVIOUS_IMAGE_LIMITATION]}
    original['memory_limits_mib']['db'] = 896
    original['steady_container_ceiling_mib'] = sum(original['memory_limits_mib'].values())
    candidate = copy.deepcopy(original)
    candidate['memory_limits_mib'].update({name: values[1] for name, values in policy.MEMORY_CHANGES.items()})
    candidate.update(qualification_status=policy.PROFILE_STATUS, qualification_scope=policy.PROFILE_SCOPE)
    candidate['evidence'].update(policy.PROFILE_EVIDENCE)
    candidate['limitations'] = policy.PROFILE_LIMITATIONS + ['Do not delete data', policy.CURRENT_IMAGE_LIMITATION]
    return original, candidate


def overlay_sources() -> tuple[str, str]:
    old, new = ['services:'], ['services:']
    for service, (before, after) in policy.MEMORY_CHANGES.items():
        old.append(f'  {service}:\n    mem_limit: {before}m\n    memswap_limit: {before}m')
        new.append(f'  {service}:\n    mem_limit: {after}m\n    memswap_limit: {after}m')
        if service in policy.REDIS_COMMANDS:
            new.append(policy.REDIS_COMMANDS[service])
    for rows in (old, new):
        rows.append('  db:\n    mem_limit: 896m\n    memswap_limit: 896m')
    return '\n'.join(old), '\n'.join(new)


def base_compose() -> str:
    return (f'EXPECTED_DATABASE_SCHEMA_REVISION: ${{EXPECTED_DATABASE_SCHEMA_REVISION:-{policy.SOURCE}}}\n'
            '--maxmemory ${REDIS_BROKER_MAXMEMORY:-512mb}\n'
            '--maxmemory ${REDIS_CACHE_MAXMEMORY:-256mb}\n')


class DocumentSourcePolicyTests(unittest.TestCase):
    def test_full_dependency_inputs_allowed_but_unreviewed_persistent_paths_rejected(self):
        rejected = ['backend/alembic/versions/0138_verified_portal_lookup.py',
                    'backend/alembic/versions/0141_unreviewed.py', 'docker-compose.prod.yml',
                    'backend/app/core/config/another_setting.py', 'backend/app/infrastructure/database/other_models.py',
                    'backend/app/infrastructure/processing/celery_app.py', 'backend/app/infrastructure/storage/repository.py',
                    'nginx/nginx.conf', 'tooling/deployment-profiles/other.json']
        allowed = list(policy.PERSISTENT_PATHS) + ['backend/requirements.lock', 'frontend/package-lock.json',
                  'backend/Dockerfile', 'frontend/Dockerfile']
        self.assertEqual(policy.forbidden_additive_paths(rejected + allowed), rejected)

    def test_only_exact_nullable_fields_and_template_defaults_are_admitted(self):
        for path in policy.FIELD_ADDITIONS:
            old, new = field_sources(path)
            with self.subTest(path=path):
                policy.validate_field_additions(path, old, new)
                with self.assertRaisesRegex(ValueError, 'unreviewed_persistent_source'):
                    policy.validate_field_additions(path, old, new.replace('unchanged', 'mutated'))
                with self.assertRaisesRegex(ValueError, 'unreviewed_persistent_source'):
                    policy.validate_field_additions(path, old, new + '    unrelated: bool = True\n')
                with self.assertRaisesRegex(ValueError, 'already_present'):
                    policy.validate_field_additions(path, new, new)
        for path, replacement in [('backend/app/infrastructure/database/models.py', ('nullable=True', 'nullable=False')),
                                  ('backend/app/infrastructure/database/communications_models.py', ('JSONB,', 'Text,')),
                                  ('backend/app/core/config/settings.py', ('pending_v1', 'other_template'))]:
            old, new = field_sources(path)
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, 'nullable_field_or_template'):
                policy.validate_field_additions(path, old, new.replace(*replacement))

    def test_facade_split_imports_preserve_exact_registration_aliases(self):
        path = 'backend/app/infrastructure/database/models.py'
        old, new = field_sources(path)
        aliases = ['traveller_returning_draft_models', 'company_directory_queue',
                   'company_data_export_models', 'traveller_reuse_models']
        new = new.replace(FACADE_IMPORTS, ''.join(f'from app.infrastructure.database import {name} as _{name}\n' for name in aliases))
        policy.validate_field_additions(path, old, new)
        with self.assertRaisesRegex(ValueError, 'registration_imports'):
            policy.validate_field_additions(path, old, new.replace('as _company_directory_queue', 'as changed_alias'))
        with self.assertRaisesRegex(ValueError, 'unreviewed_persistent_source'):
            policy.validate_field_additions(path, old, new + '\nimport unexpected\n')

    def test_exact_schema_default_and_no_other_compose_mutation(self):
        old = base_compose()
        new = old.replace(policy.SOURCE, policy.TARGET)
        policy.validate_compose(old, new)
        for change in (new + 'volumes: {db: different}\n', new.replace('512mb', '1024mb'), new.replace(policy.TARGET, policy.SOURCE)):
            with self.subTest(change=change), self.assertRaises(ValueError):
                policy.validate_compose(old, change)
        with self.assertRaisesRegex(ValueError, 'previous_redis'):
            policy.validate_compose(old.replace('512mb', '1024mb'), new)

    def test_exact_ram_redis_auth_persistence_and_cpu_are_bound(self):
        old, new = overlay_sources()
        policy.validate_overlay(old, new)
        variants = [new.replace('1024m', '2048m'), new.replace('384mb', '512mb'),
                    new.replace('128mb', '64mb'), new.replace('appendonly yes', 'appendonly no'),
                    new.replace('noeviction', 'allkeys-lru'), new.replace('${REDIS_BROKER_PASSWORD:-${REDIS_PASSWORD}}', 'new-secret'),
                    new + '\n    cpus: 6', new.replace('mem_limit: 896m\n    memswap_limit: 896m', 'mem_limit: 900m\n    memswap_limit: 900m')]
        for changed in variants:
            with self.subTest(changed=changed), self.assertRaisesRegex(ValueError, 'resource_overlay'):
                policy.validate_overlay(old, changed)

    def test_profile_preserves_reserve_other_caps_and_honest_qualification(self):
        old, new = profile_sources()
        policy.validate_profile(json.dumps(old), json.dumps(new))
        variants = [{'host_reserve_mib': 1024}, {'qualification_status': 'qualified'},
                    {'memory_limits_mib': {**new['memory_limits_mib'], 'db': 900}},
                    {'limitations': []}, {'evidence': {**new['evidence'], 'existing': 'overwritten.json'}},
                    {'limitations': [value.replace('requires its separate image-bound migration and resource receipts',
                                                  'requires no separate checks') for value in new['limitations']]},
                    {'limitations': [value.replace(policy.CURRENT_IMAGE_LIMITATION, policy.PREVIOUS_IMAGE_LIMITATION)
                                     for value in new['limitations']]},
                    {'worker_children_each': 2}, {'worker_children_each': True}]
        for changed in variants:
            with self.subTest(changed=changed), self.assertRaisesRegex(ValueError, 'resource_profile'):
                policy.validate_profile(json.dumps(old), json.dumps({**new, **changed}))

    def test_existing_task_body_may_continue_but_queue_signature_and_retry_contract_stay(self):
        new = TASK_BEFORE.replace('return run(send_batch_id)', 'continue_same_batch(send_batch_id)') + TASK_ADDITION
        policy.validate_task_change(policy.TASK_MODULE, TASK_BEFORE, new)
        for changed in (new.replace('send_batch_id: str', 'send_batch_id: str, extra: str'),
                        new.replace('queue="whatsapp"', 'queue="other"', 1),
                        new.replace('max_retries=2', 'max_retries=4', 1)):
            with self.assertRaisesRegex(ValueError, 'existing_queued'):
                policy.validate_task_change(policy.TASK_MODULE, TASK_BEFORE, changed)
        for changed in (new.replace('batch_id: str) -> None:\n    return run_update', 'batch_id: int) -> None:\n    return run_update'),
                        new.replace('soft_time_limit=9 * 60', 'soft_time_limit=20 * 60'),
                        new + TASK_ADDITION, TASK_BEFORE):
            with self.assertRaises(ValueError):
                policy.validate_task_change(policy.TASK_MODULE, TASK_BEFORE, changed)
        with self.assertRaisesRegex(ValueError, 'unreviewed_new'):
            policy.validate_task_change('backend/app/other.py', '', TASK_ADDITION)

    def test_manifest_keeps_worker_topology_and_requires_0138_baseline(self):
        old = {'version': 1, 'schema_revision': policy.SOURCE, 'previous_schema_revision': 'older',
               'deployment_kind': 'previous_kind', 'worker_nodes': policy.WORKERS}
        new = {**old, 'schema_revision': policy.TARGET, 'previous_schema_revision': policy.SOURCE, 'deployment_kind': policy.KIND}
        policy.validate_manifest(json.dumps(old), json.dumps(new))
        with self.assertRaisesRegex(ValueError, 'release_manifest'):
            policy.validate_manifest(json.dumps(old), json.dumps({**new, 'worker_nodes': {'worker': 'other'}}))
        with self.assertRaisesRegex(ValueError, 'release_manifest'):
            policy.validate_manifest(json.dumps(old), json.dumps({**new, 'version': True}))
        with self.assertRaisesRegex(ValueError, 'previous_schema'):
            policy.validate_manifest(json.dumps({**old, 'schema_revision': '0129_travel_tracker'}), json.dumps(new))


class GitAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)
        self.git('init', '-q')
        old_manifest = {'version': 1, 'schema_revision': policy.SOURCE, 'previous_schema_revision': 'older',
                        'deployment_kind': 'previous_kind', 'worker_nodes': policy.WORKERS}
        old_profile, new_profile = profile_sources()
        old_overlay, new_overlay = overlay_sources()
        self.old = {path: field_sources(path)[0] for path in policy.FIELD_ADDITIONS}
        self.old.update({policy.MANIFEST: json.dumps(old_manifest), policy.BASE_COMPOSE: base_compose(),
                         policy.PROFILE: json.dumps(old_profile), policy.OVERLAY: old_overlay,
                         policy.TASK_MODULE: TASK_BEFORE,
                         'backend/app/infrastructure/processing/celery_app.py': 'SCHEDULE = 5\n',
                         'backend/alembic/versions/0138_verified_portal_lookup.py': 'revision = "0138_verified_portal_lookup"\n',
                         'backend/requirements.lock': 'unchanged==1\n'})
        for path, text in self.old.items():
            self.write(path, text)
        self.previous = self.commit()
        self.new = {path: field_sources(path)[1] for path in policy.FIELD_ADDITIONS}
        self.new.update({policy.MANIFEST: json.dumps({**old_manifest, 'deployment_kind': policy.KIND,
                         'schema_revision': policy.TARGET, 'previous_schema_revision': policy.SOURCE}),
                         policy.BASE_COMPOSE: base_compose().replace(policy.SOURCE, policy.TARGET),
                         policy.PROFILE: json.dumps(new_profile), policy.OVERLAY: new_overlay,
                         policy.TASK_MODULE: TASK_BEFORE + TASK_ADDITION,
                         'backend/requirements.lock': 'changed-full-ci==2\n'})
        # Migration AST qualification belongs to source_contract; this fixture
        # independently exercises Git identity, old/new source and path admission.
        self.new.update({f'backend/alembic/versions/{name}.py': f'revision = "{name}"\n' for name in policy.CHAIN})
        for path, text in self.new.items():
            self.write(path, text)
        self.revision = self.commit()
        self.contract = self.enterContext(patch.object(policy, 'source_contract', return_value={}))

    def git(self, *arguments: str) -> str:
        return subprocess.run(['git', '-C', str(self.root), *arguments], check=True, capture_output=True, text=True, encoding='utf-8').stdout.strip()

    def write(self, path: str, text: str):
        file = self.root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text, encoding='utf-8')

    def commit(self) -> str:
        self.git('add', '.')
        self.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.test', 'commit', '-qm', 'fixture')
        return self.git('rev-parse', 'HEAD')

    def admit(self):
        policy.validate_additive_source(self.root, self.revision, self.previous)

    def test_clean_commit_accepts_reviewed_changes_and_full_dependencies(self):
        self.admit()
        self.contract.assert_called_once_with(self.root)

    def test_dirty_tracked_and_untracked_inputs_are_rejected(self):
        self.write('untracked.py', 'print("unreviewed")')
        with self.assertRaisesRegex(ValueError, 'source_modified'):
            self.admit()
        (self.root / 'untracked.py').unlink()
        self.write(policy.TASK_MODULE, self.new[policy.TASK_MODULE] + '\n# dirty\n')
        with self.assertRaisesRegex(ValueError, 'source_modified'):
            self.admit()

    def test_candidate_sha_cannot_be_substituted(self):
        with self.assertRaisesRegex(ValueError, 'source_revision'):
            policy.validate_additive_source(self.root, 'f' * 40, self.previous)

    def test_unreviewed_scheduler_source_change_rejected_before_contract_read(self):
        self.write('backend/app/infrastructure/processing/celery_app.py', 'SCHEDULE = 10\n')
        self.revision = self.commit()
        with self.assertRaisesRegex(ValueError, 'persistent_contract'):
            self.admit()
        self.contract.assert_not_called()

    def test_existing_migration_changes_are_rejected(self):
        self.write('backend/alembic/versions/0138_verified_portal_lookup.py', 'revision = "mutated"\n')
        self.revision = self.commit()
        with self.assertRaisesRegex(ValueError, 'persistent_contract'):
            self.admit()

    def test_unrelated_model_change_in_allowed_file_is_rejected(self):
        path = 'backend/app/infrastructure/database/communications_models.py'
        self.write(path, self.new[path] + '\nclass OtherModel:\n    changed = True\n')
        self.revision = self.commit()
        with self.assertRaisesRegex(ValueError, 'persistent_source_mutation'):
            self.admit()

    def test_new_task_in_unrelated_module_is_rejected(self):
        self.write('backend/app/extra_tasks.py', TASK_ADDITION)
        self.revision = self.commit()
        with self.assertRaisesRegex(ValueError, 'unreviewed_new_queued'):
            self.admit()


if __name__ == '__main__':
    unittest.main()
