"""Narrow persistent-contract admission for the reviewed 0135 -> 0138 release."""
from __future__ import annotations

import ast
from pathlib import Path

from mcp_direct_build import command
from mcp_direct_state import WORKERS
from release_code_update import COMPATIBILITY_PATHS, task_contract
from release_companies_traveller_contract import CHAIN, SOURCE, TARGET, source_contract
from release_manifest import load_release_manifest
from release_retained_update import (
    ADDITIONAL_CONTRACT_PATHS,
    FULL_BUILD_PATHS,
    ROUTE_ALLOWLIST,
    require,
    validate_route_allowlist,
)

PERSISTENT_PATHS = frozenset({
    'docker-compose.yml', ROUTE_ALLOWLIST,
    'backend/app/core/config/release_manifest.json',
    'backend/app/domain/entities/entities.py',
    'backend/app/infrastructure/database/models.py',
    'backend/app/infrastructure/database/company_directory_models.py',
    'backend/app/infrastructure/database/company_directory_queue.py',
    'backend/app/infrastructure/database/company_directory_invalidation.py',
    'backend/app/infrastructure/database/traveller_returning_draft_models.py',
    'backend/app/infrastructure/processing/celery_app.py',
    *(f'backend/alembic/versions/{revision}.py' for revision in CHAIN),
    *(f'backend/app/infrastructure/database/traveller_{name}.py' for name in (
        'claim_models', 'document_models')),
})
NEW_TASK_MODULES = {
    'backend/app/infrastructure/travellers/draft_tasks.py',
    'backend/app/infrastructure/travellers/directory_tasks.py',
}
TASK_ADDITIONS = {
    'backend/app/infrastructure/travellers/draft_tasks.py': task_contract(
        '@celery_app.task(name="travellers.returning_drafts", queue="passport_ocr", soft_time_limit=50, time_limit=60)\n'
        'def returning_drafts(): pass'),
    'backend/app/infrastructure/travellers/directory_tasks.py': task_contract(
        '@celery_app.task(name="companies.refresh_directory", queue="passport_ocr", soft_time_limit=30, time_limit=40)\n'
        'def refresh_company_directory(): pass'),
}
INCLUDES = {'app.infrastructure.travellers.draft_tasks', 'app.infrastructure.travellers.directory_tasks'}
SCHEDULES = {
    'process-returning-drafts': ('travellers.returning_drafts', 5),
    'refresh-company-directory': ('companies.refresh_directory', 5),
}


def forbidden_additive_paths(paths: list[str]) -> list[str]:
    return [path for path in paths if path not in PERSISTENT_PATHS and not path.startswith(FULL_BUILD_PATHS)]


def validate_scheduler(old: str, new: str) -> None:
    """Remove only the two reviewed schedules/includes; old AST must survive."""
    original, candidate = ast.parse(old), ast.parse(new)
    found_includes: set[str] = set()
    found_schedules: set[str] = set()
    for node in ast.walk(candidate):
        if isinstance(node, ast.List):
            removed = [item for item in node.elts if isinstance(item, ast.Constant) and item.value in INCLUDES]
            names = {item.value for item in removed}
            require(len(names) == len(removed) and not found_includes.intersection(names), 'duplicate_traveller_include')
            found_includes.update(item.value for item in removed if isinstance(item.value, str))
            node.elts = [item for item in node.elts if item not in removed]
        if isinstance(node, ast.Dict):
            keep = []
            for key, value in zip(node.keys, node.values):
                name = key.value if isinstance(key, ast.Constant) else None
                if name in SCHEDULES:
                    task, seconds = SCHEDULES[name]
                    require(ast.literal_eval(value) == {
                        'task': task, 'schedule': seconds,
                        'options': {'queue': 'passport_ocr', 'expires': seconds},
                    }, 'traveller_schedule_contract_changed')
                    require(name not in found_schedules, 'duplicate_traveller_schedule')
                    found_schedules.add(name)
                else:
                    keep.append((key, value))
            node.keys, node.values = [pair[0] for pair in keep], [pair[1] for pair in keep]
    require(found_includes == INCLUDES and found_schedules == set(SCHEDULES), 'traveller_schedules_incomplete')
    require(ast.dump(original) == ast.dump(candidate), 'existing_scheduler_contract_changed')


def validate_task_change(path: str, old: str, new: str) -> None:
    before, after = task_contract(old), task_contract(new)
    require(all(after.get(name) == contract for name, contract in before.items()), 'existing_queued_task_contract_changed')
    require(before == after or path in NEW_TASK_MODULES and not old, 'unreviewed_new_queued_task_contract')
    if path in NEW_TASK_MODULES and not old:
        require(after == TASK_ADDITIONS[path], 'new_queued_task_contract_changed')


def validate_additive_source(source: Path, revision: str, previous: str) -> None:
    def git(*args: str) -> str:
        return command('git', '-C', str(source), *args)

    require(git('rev-parse', 'HEAD') == revision, 'candidate_source_revision_changed')
    require(not git('status', '--porcelain', '--untracked-files=no'), 'candidate_source_modified')
    git('merge-base', '--is-ancestor', previous, revision)
    paths = git('diff', '--name-only', previous, revision, '--',
                *COMPATIBILITY_PATHS, *ADDITIONAL_CONTRACT_PATHS).splitlines()
    require(not forbidden_additive_paths(paths), 'unreviewed_additive_persistent_contract')
    source_contract(source)  # Exact ordered revision chain and source hashes.
    manifest = load_release_manifest(source / 'backend/app/core/config/release_manifest.json')
    require(manifest['worker_nodes'] == WORKERS, 'worker_topology_changed')
    validate_route_allowlist(source)
    for path in paths:
        if path.startswith('backend/alembic/'):
            require(not git('ls-tree', '--name-only', previous, '--', path), 'existing_migration_modified')
    compose = 'docker-compose.yml'
    require(git('show', f'{previous}:{compose}').replace(SOURCE, TARGET) == (source / compose).read_text().strip(),
            'compose_change_exceeds_exact_schema_default')
    scheduler = 'backend/app/infrastructure/processing/celery_app.py'
    validate_scheduler(git('show', f'{previous}:{scheduler}'), (source / scheduler).read_text())
    for path in git('diff', '--name-only', previous, revision, '--', 'backend/app').splitlines():
        if path.endswith('.py'):
            old = git('show', f'{previous}:{path}') if git('ls-tree', '--name-only', previous, '--', path) else ''
            new = (source / path).read_text() if (source / path).is_file() else ''
            validate_task_change(path, old, new)
