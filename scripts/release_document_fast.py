"""Lower-assurance local-build evidence for the exact document distribution additive lane.

This does not admit arbitrary schema changes or grant Full CI qualification.
The live-runtime bases are retained; Dockerfile/native security changes are not
applied by this code-copy build. Every resume reuses the same images and proof.
"""
from __future__ import annotations

import json
import os
import re
import stat
from pathlib import Path
from typing import Any, cast

from mcp_direct_build import command, contract_digest
from release_document_distribution_contract import SOURCE, TARGET, source_contract
from release_mcp_database import digest_json
from release_reliability import file_sha256
from release_retained_update import require

CHECKS = frozenset({
    'source_upgrade', 'intermediate_resume', 'idempotent_target', 'lock_failure',
    'historical_rows_catalog_acl_preserved', 'wrong_baseline_rejected',
    'new_columns_null', 'runtime_grants_verified',
})


def validate_dependencies(source: Path, previous: str, revision: str) -> None:
    changed = command('git', '-C', str(source), 'diff', '--name-only', previous, revision,
                      '--', 'backend/requirements*')
    require(not changed, 'fast_additive_backend_dependencies_must_be_unchanged')


def binding(source: Path, revision: str, record: dict[str, Any]) -> dict[str, Any]:
    return {
        'version': 1, 'mode': 'fast', 'source_revision': revision,
        'operator_selected_vps_build': True,
        'source_contract_sha256': digest_json(source_contract(source)),
        'backend_api_contract_sha256': contract_digest((source / 'backend/contracts/api.openapi.json').read_bytes()),
        'image_ids': dict(record['image_ids']),
        'base_image_ids': {name: record['live'][name]['Image'] for name in ('backend', 'frontend')},
        'runtime_inherited_from_previous_images': True,
        'dockerfile_native_security_changes_applied': False,
        'full_ci_qualified': False,
    }


def verify_images(source: Path, revision: str, record: dict[str, Any]) -> dict[str, str]:
    expected = binding(source, revision, record)
    require(json.dumps(record.get('fast_document_binding'), sort_keys=True) == json.dumps(expected, sort_keys=True), 'fast_additive_build_binding_changed')
    images = record['image_ids']
    require(set(images) == {'backend', 'frontend'} and all(
        isinstance(value, str) and re.fullmatch('sha256:[a-f0-9]{64}', value) for value in images.values()
    ), 'fast_additive_image_inventory_invalid')
    inspected = json.loads(command('docker', 'image', 'inspect', *images.values()))
    by_id = {value['Id']: value for value in inspected}
    require(set(by_id) == set(images.values()), 'fast_additive_image_inventory_changed')
    builds = record.get('fast_build', {})
    require(set(builds) == set(images), 'fast_additive_build_receipt_missing')
    for name, image_id in images.items():
        build = builds[name]
        require(build.get('image_id') == image_id and build.get('base_image_id') == expected['base_image_ids'][name]
                and type(build.get('exit_code')) is int and build['exit_code'] == 0 and build.get('oom_killed') is False,
                'fast_additive_build_receipt_changed')
        config = by_id[image_id]['Config']
        values = dict(item.split('=', 1) for item in config.get('Env', []))
        require(config.get('Labels', {}).get('org.opencontainers.image.revision') == revision
                and config.get('User') == '1001:1001' and config.get('WorkingDir') == '/app'
                and config.get('Entrypoint') in (None, []), 'fast_additive_image_config_changed')
        if name == 'backend':
            require(values.get('APP_REVISION') == revision
                    and values.get('EXPECTED_DATABASE_SCHEMA_REVISION') == TARGET
                    and config.get('Cmd') == ['gunicorn', '--config', 'gunicorn.conf.py', 'app.main:app']
                    and build.get('verified_api_contract_sha256') == expected['backend_api_contract_sha256'],
                    'fast_additive_backend_proof_changed')
        else:
            require(values.get('NEXT_PUBLIC_APP_REVISION') == revision
                    and config.get('Cmd') == ['node', 'server.js'], 'fast_additive_frontend_proof_changed')
        verify_builder(build['container_id'])
        if name == 'frontend':
            verify_builder(build['runtime_container_id'])
    return dict(images)


def verify_builder(identifier: str) -> None:
    require(isinstance(identifier, str) and re.fullmatch('[a-f0-9]{64}', identifier) is not None,
            'fast_additive_builder_identity_invalid')
    rows = json.loads(command('docker', 'inspect', identifier))
    require(len(rows) == 1 and rows[0]['Id'] == identifier, 'fast_additive_builder_changed')
    state = rows[0]['State']
    require(state.get('Running') is False and type(state.get('ExitCode')) is int and state['ExitCode'] == 0
            and state.get('OOMKilled') is False and state.get('Dead') is not True
            and rows[0].get('RestartCount', 0) == 0, 'fast_additive_builder_not_successfully_stopped')


def read_rehearsal(path: Path, expected: dict[str, Any]) -> dict[str, Any]:
    info = path.stat(follow_symlinks=False)
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and 0 < info.st_size <= 65536
            and not (os.name == 'posix' and info.st_mode & 0o077), 'fast_rehearsal_receipt_not_private_regular_file')
    receipt = json.loads(path.read_text(encoding='utf-8'))
    require(isinstance(receipt, dict) and type(receipt.get('version')) is int and receipt['version'] == 1
            and receipt.get('status') == 'passed'
            and receipt.get('source_revision') == expected['source_revision']
            and receipt.get('backend_image_id') == expected['image_ids']['backend']
            and receipt.get('source_contract_sha256') == expected['source_contract_sha256']
            and receipt.get('source_schema') == SOURCE and receipt.get('target_schema') == TARGET
            and receipt.get('full_ci_qualified') is False and receipt.get('owned_resources_removed') is True,
            'fast_rehearsal_receipt_binding_changed')
    checks = receipt.get('checks')
    require(isinstance(checks, dict) and set(checks) == CHECKS and all(value is True for value in checks.values()),
            'fast_rehearsal_checks_incomplete')
    return {'filename': path.name, 'sha256': file_sha256(path), 'evidence': receipt}


def verify_rehearsal(directory: Path, record: dict[str, Any]) -> None:
    saved = record.get('fast_document_migration_rehearsal')
    require(isinstance(saved, dict) and saved.get('filename') == 'fast-document-migration-rehearsal.json',
            'fast_rehearsal_required_before_live_migration')
    saved = cast(dict[str, Any], saved)
    actual = read_rehearsal(directory / saved['filename'], record['fast_document_binding'])
    require(saved == actual, 'fast_rehearsal_receipt_changed')
