"""Source admission for the reviewed 0138 -> 0140 document release.

This is source admission, not runtime qualification or permission to send. Every
old persistent definition survives, apart from the explicit additions below.
The executor requires signed Full images or the explicitly selected operator
VPS Fast build with its separate image-bound migration and resource evidence.
"""
from __future__ import annotations

import ast
import copy
import json
import subprocess
from pathlib import Path

from mcp_direct_state import WORKERS
from release_code_update import COMPATIBILITY_PATHS, task_contract
from release_document_distribution_contract import (
    CHAIN,
    KIND,
    SOURCE,
    TARGET,
    source_contract,
)
from release_retained_update import ADDITIONAL_CONTRACT_PATHS, FULL_BUILD_PATHS, require

MANIFEST = 'backend/app/core/config/release_manifest.json'
BASE_COMPOSE = 'docker-compose.yml'
OVERLAY = 'docker-compose.kvm4.yml'
PROFILE = 'tooling/deployment-profiles/kvm4.json'
TASK_MODULE = 'backend/app/infrastructure/whatsapp/tasks.py'
FIELD_ADDITIONS = {
    'backend/app/domain/entities/entities.py': ('PassportSubmission', (
        'display_name: str | None = None',)),
    'backend/app/infrastructure/database/models.py': ('PassportSubmissionModel', (
        'display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)',)),
    'backend/app/infrastructure/database/communications_models.py': ('WhatsAppMessageLogModel', (
        'document_update_context: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)',)),
    'backend/app/core/config/settings.py': ('Settings', (
        'whatsapp_document_update_template_name: str = "pending_v1"',
        'whatsapp_document_update_template_language: str = "en"',)),
}
PERSISTENT_PATHS = frozenset({MANIFEST, BASE_COMPOSE, OVERLAY, PROFILE, *FIELD_ADDITIONS,
    *(f'backend/alembic/versions/{revision}.py' for revision in CHAIN)})
MEMORY_CHANGES = {'worker': (384, 1024), 'frontend': (512, 256),
                  'redis-broker': (1152, 896), 'redis-cache': (320, 192)}
REDIS_COMMANDS = {
    'redis-broker': '''    command: >-
      redis-server
      --requirepass ${REDIS_BROKER_PASSWORD:-${REDIS_PASSWORD}}
      --appendonly yes
      --appendfsync everysec
      --maxmemory 384mb
      --maxmemory-policy noeviction''',
    'redis-cache': '''    command: >-
      redis-server
      --requirepass ${REDIS_CACHE_PASSWORD:-${REDIS_PASSWORD}}
      --save ""
      --appendonly no
      --maxmemory 128mb
      --maxmemory-policy allkeys-lru''',
}
NEW_TASK = task_contract('''@celery_app.task(
    bind=True, name="whatsapp.process_document_update_broadcast", queue="whatsapp",
    max_retries=2, default_retry_delay=10, soft_time_limit=9 * 60, time_limit=10 * 60)
def process_document_update_broadcast(self: _BoundTask, *, batch_id: str) -> None: pass
''')
PROFILE_STATUS = 'candidate_pending_final_application_and_lifecycle_checks'
PROFILE_SCOPE = 'historical_qualification_plus_20261015_installed_image_isolated_redis_and_frontend_donor_pressure_checks_pending_exact_release'
PROFILE_EVIDENCE = {
    'document_delivery_rebalance': 'docs/remediation/document-delivery-rebalance-evidence.json',
    'redis_dataset_transition': 'docs/remediation/redis-dataset-transition-evidence.json',
}
PROFILE_LIMITATIONS = [
    'The 20261015 donor probes used installed images and synthetic data, not final-release qualification; activation remains blocked pending final application and lifecycle checks',
    'Broker dataset allowance falls from 512 to 384 MiB and evictable cache from 256 to 128 MiB; broker remains noeviction with AOF persistence',
]
PREVIOUS_IMAGE_LIMITATION = 'Qualification used backend image 0066ad357a08c4b207fa93bfa12e6111a90ebcac3514b4edbbdeb31a66db0f67; CI must independently qualify and sign the exact pushed-revision images'
CURRENT_IMAGE_LIMITATION = 'Historical qualification used backend image 0066ad357a08c4b207fa93bfa12e6111a90ebcac3514b4edbbdeb31a66db0f67; Full mode requires signed exact-revision CI images, while the explicitly selected document VPS Fast lane requires its separate image-bound migration and resource receipts'


def forbidden_additive_paths(paths: list[str]) -> list[str]:
    """Admit reviewed build paths; the executor separately binds Full/Fast evidence."""
    return [path for path in paths if path not in PERSISTENT_PATHS and not path.startswith(FULL_BUILD_PATHS)]


def _normalize_facade_imports(module: ast.Module) -> None:
    # Ruff split/reordered only these pre-existing model-registration imports.
    # Compare their exact aliases and all other statements, not arbitrary imports.
    names = {'company_data_export_models', 'company_directory_queue',
             'traveller_returning_draft_models', 'traveller_reuse_models'}
    found: list[str] = []
    body = []
    for node in module.body:
        if isinstance(node, ast.ImportFrom) and node.module == 'app.infrastructure.database' and node.level == 0:
            removed = [item for item in node.names if item.name in names]
            found.extend(ast.dump(item) for item in removed)
            node.names = [item for item in node.names if item.name not in names]
            if not node.names:
                continue
        body.append(node)
    expected = [ast.dump(ast.alias(name=name, asname='_' + name)) for name in names]
    require(sorted(found) == sorted(expected), 'model_registration_imports_changed')
    module.body = body


def validate_field_additions(path: str, old: str, new: str) -> None:
    class_name, declarations = FIELD_ADDITIONS[path]
    original, candidate = ast.parse(old), ast.parse(new)
    old_classes = [node for node in original.body if isinstance(node, ast.ClassDef) and node.name == class_name]
    new_classes = [node for node in candidate.body if isinstance(node, ast.ClassDef) and node.name == class_name]
    require(len(old_classes) == len(new_classes) == 1, 'persistent_class_missing_or_duplicated')
    for declaration in declarations:
        expected = ast.parse(declaration).body[0]
        assert isinstance(expected, ast.AnnAssign) and isinstance(expected.target, ast.Name)
        def matches(node: ast.AST, field_name: str = expected.target.id) -> bool:
            return isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == field_name
        require(not any(matches(node) for node in old_classes[0].body), 'persistent_addition_already_present')
        matches_new = [node for node in new_classes[0].body if matches(node)]
        require(len(matches_new) == 1 and ast.dump(matches_new[0]) == ast.dump(expected),
                'reviewed_nullable_field_or_template_changed')
        new_classes[0].body.remove(matches_new[0])
    if path == 'backend/app/infrastructure/database/models.py':
        _normalize_facade_imports(original)
        _normalize_facade_imports(candidate)
    require(ast.dump(original) == ast.dump(candidate), 'unreviewed_persistent_source_mutation')


def _normalized_lines(value: str) -> str:
    return '\n'.join(line.rstrip() for line in value.splitlines()
                     if line.strip() and not line.lstrip().startswith('#'))


def _same_json(left: object, right: object) -> bool:
    # Python considers True == 1; release metadata must preserve JSON types too.
    return json.dumps(left, sort_keys=True) == json.dumps(right, sort_keys=True)


def _replace_once(value: str, old: str, new: str, reason: str) -> str:
    require(value.count(old) == 1, reason)
    return value.replace(old, new)


def validate_compose(old: str, new: str) -> None:
    old, new = _normalized_lines(old), _normalized_lines(new)
    declaration = 'EXPECTED_DATABASE_SCHEMA_REVISION: ${EXPECTED_DATABASE_SCHEMA_REVISION:-'
    expected = _replace_once(old, declaration + SOURCE + '}', declaration + TARGET + '}',
                             'exact_previous_schema_default_required')
    for domain, maximum in (('BROKER', 512), ('CACHE', 256)):
        require(old.count(f'--maxmemory ${{REDIS_{domain}_MAXMEMORY:-{maximum}mb}}') == 1,
                'previous_redis_dataset_contract_changed')
    require(expected == new, 'compose_change_exceeds_exact_schema_default')


def validate_overlay(old: str, new: str) -> None:
    expected = _normalized_lines(old)
    for service, (before, after) in MEMORY_CHANGES.items():
        original = f'  {service}:\n    mem_limit: {before}m\n    memswap_limit: {before}m'
        replacement = f'  {service}:\n    mem_limit: {after}m\n    memswap_limit: {after}m'
        if service in REDIS_COMMANDS:
            replacement += '\n' + REDIS_COMMANDS[service]
        expected = _replace_once(expected, original, replacement, 'previous_memory_contract_changed')
    require(expected == _normalized_lines(new), 'unreviewed_resource_overlay_change')


def validate_profile(old: str, new: str) -> None:
    original, candidate = json.loads(old), json.loads(new)
    expected = copy.deepcopy(original)
    require(original.get('qualification_status') == 'qualified', 'previous_profile_not_qualified')
    for service, (before, after) in MEMORY_CHANGES.items():
        require(expected['memory_limits_mib'].get(service) == before, 'previous_memory_contract_changed')
        expected['memory_limits_mib'][service] = after
    require(sum(expected['memory_limits_mib'].values()) == original['steady_container_ceiling_mib'],
            'steady_memory_total_changed')
    require(not set(PROFILE_EVIDENCE).intersection(original['evidence']), 'resource_evidence_already_present')
    expected.update(qualification_status=PROFILE_STATUS, qualification_scope=PROFILE_SCOPE)
    expected['evidence'].update(PROFILE_EVIDENCE)
    require(expected['limitations'].count(PREVIOUS_IMAGE_LIMITATION) == 1,
            'previous_profile_image_limitation_changed')
    expected['limitations'] = PROFILE_LIMITATIONS + [
        CURRENT_IMAGE_LIMITATION if value == PREVIOUS_IMAGE_LIMITATION else value for value in expected['limitations']
    ]
    require(_same_json(expected, candidate), 'unreviewed_resource_profile_change')


def validate_manifest(old: str, new: str) -> None:
    original, candidate = json.loads(old), json.loads(new)
    require(original.get('schema_revision') == SOURCE and original.get('worker_nodes') == WORKERS,
            'previous_schema_or_worker_contract_changed')
    expected = {**original, 'schema_revision': TARGET, 'previous_schema_revision': SOURCE, 'deployment_kind': KIND}
    require(_same_json(candidate, expected), 'unreviewed_release_manifest_change')


def _unique_task_contract(source: str) -> dict[str, str]:
    count = sum(1 for node in ast.walk(ast.parse(source))
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
                    isinstance(item, ast.Call) and (
                        isinstance(item.func, ast.Attribute) and item.func.attr == 'task'
                        or isinstance(item.func, ast.Name) and item.func.id == 'shared_task')
                    for item in node.decorator_list))
    contracts = task_contract(source)
    require(len(contracts) == count, 'duplicate_queued_task_name')
    return contracts


def validate_task_change(path: str, old: str, new: str) -> None:
    before, after = _unique_task_contract(old), _unique_task_contract(new)
    require(all(after.get(name) == contract for name, contract in before.items()),
            'existing_queued_task_contract_changed')
    if path == TASK_MODULE:
        require(not set(before).intersection(NEW_TASK) and after == {**before, **NEW_TASK},
                'new_document_update_task_contract_changed')
    else:
        require(before == after, 'unreviewed_new_queued_task_contract')


def validate_additive_source(source: Path, revision: str, previous: str) -> None:
    def git(*args: str) -> str:
        # Git blobs are repository UTF-8 even on a Windows host with an ANSI
        # locale. Decoding them differently from candidate files breaks binding.
        result = subprocess.run(['git', '-C', str(source), *args], capture_output=True,
                                text=True, encoding='utf-8', timeout=60, check=False)
        require(result.returncode == 0, 'candidate_git_identity_or_ancestry_invalid')
        return result.stdout.strip()

    def candidate(path: str) -> str:
        file = source / path
        require(file.is_file() and not file.is_symlink() and file.resolve().is_relative_to(source.resolve()),
                'candidate_contract_file_missing_or_linked')
        return file.read_text(encoding='utf-8')

    require(git('rev-parse', 'HEAD') == revision, 'candidate_source_revision_changed')
    require(not git('status', '--porcelain', '--untracked-files=all'), 'candidate_source_modified')
    git('merge-base', '--is-ancestor', previous, revision)
    paths = git('diff', '--name-only', previous, revision, '--',
                *COMPATIBILITY_PATHS, *ADDITIONAL_CONTRACT_PATHS).splitlines()
    require(not forbidden_additive_paths(paths), 'unreviewed_additive_persistent_contract')
    source_contract(source)  # Exact full migration ASTs, ancestry and content hashes.
    for revision_name in CHAIN:
        path = f'backend/alembic/versions/{revision_name}.py'
        require(not git('ls-tree', '--name-only', previous, '--', path), 'existing_migration_modified')
        candidate(path)
    validators = {BASE_COMPOSE: validate_compose, OVERLAY: validate_overlay,
                  PROFILE: validate_profile, MANIFEST: validate_manifest}
    for path, validator in validators.items():
        validator(git('show', f'{previous}:{path}'), candidate(path))
    for path in FIELD_ADDITIONS:
        validate_field_additions(path, git('show', f'{previous}:{path}'), candidate(path))
    task_paths = set(git('diff', '--name-only', previous, revision, '--', 'backend/app').splitlines())
    task_paths.add(TASK_MODULE)
    for path in sorted(task_paths):
        if path.endswith('.py'):
            old = git('show', f'{previous}:{path}') if git('ls-tree', '--name-only', previous, '--', path) else ''
            new = candidate(path) if (source / path).exists() else ''
            validate_task_change(path, old, new)
