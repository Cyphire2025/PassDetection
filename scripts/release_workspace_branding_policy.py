"""Fail-closed source admission for the reviewed live baseline and branding patch."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from mcp_direct_build import command
from release_code_update import COMPATIBILITY_PATHS, task_contract
from release_retained_update import ADDITIONAL_CONTRACT_PATHS, ROUTE_ALLOWLIST, require, validate_route_allowlist
from release_workspace_branding_contract import TARGET, source_contract

BASE = '98f4fb4f7ba982fc46f917d24db63d59993a74a8'
# SHA-256 of normalized Git source, populated from the reviewed release files.
REVIEWED_FILES = {'backend/alembic/versions/0141_workspace_branding.py': [None,
                                                         'f511c957f633c5bf3c2065b80270f61f89b4d4d75e5c4c3ca1e3c71f3b2d4567'],
 'backend/app/core/config/release_manifest.json': ['c299ce7831e45c560772460e88adb90425601d9a8eefa2e705300f6b5494c37f',
                                                   'cc268e4b24d58b50ec72f95c3ccd03350c96033833db061fd3ba5fe63b0fdf80'],
 'backend/app/core/config/settings.py': ['f03d2164785e577d5cdceb05d821b793fc7602a8e01d2992a3c7561d0d42d41e',
                                         'ca8a8ebd3333f588766d85071e5c963ef10dbb01e9d5ee2891d94fbe64cd9017'],
 'backend/app/domain/entities/entities.py': ['0d6ca59ea43f42daddbb686fb79f21e04c27157c589bf4227f1bc169ffdd96d2',
                                             'ff83a9b8c350d7d3bfd0b75922d67ee32bec62a7164cf1ca2d13e77e6e19e225'],
 'backend/app/infrastructure/database/communications_models.py': ['f28acf7b3c2e90f758202a18e4dcbc56bbec2d93d4db9c38e4bde3bfb58240a0',
                                                                  '1945ccceb8ee2c8e7b937eacd5370dc26cbc6bfacd80376c4cdfa42446a48297'],
 'backend/app/infrastructure/database/gc_mobile_models.py': ['d9bed4d91e3c30690de5fe575373b48a6b8a51edb7feb77527aa20b7a85fba61',
                                                             '401154b6e85d45ebbbfd2151d84e30cf50a74721c50a472ef95f5fae25536b34'],
 'backend/app/infrastructure/database/models.py': ['4c4b5d0d51d39a359fe5467a5aa26c3e7fb9eef41a5ef609036dbfcab6eb7da7',
                                                   '6d5fd4469e2b5321800a713c0bf3ecce48d0d6d3a78cd6ecbcab36f76ac90abb'],
 'backend/app/infrastructure/storage/branding_urls.py': [None,
                                                         'd6372bdb551e4def9cc5edeed8904e9edff162d39259458b5083c909a6466b22'],
 'docker-compose.yml': ['e7e44f8ad4aa6fd39c6fbbdd1befec7750470d4c64c4eac623cf308cfc861e45',
                        '37a1d21f0e313c9e0e0c3d9fde4a662743317751aae059965d01ab6eb53ea8a8'],
 'frontend/scripts/verify-whatsapp-recipient-bulk-browser.mjs': ['bfd36aa9eed6d26eca5ae998a0f73b8fd278d045008ecccba3465da7e9c8b143',
                                                                 '99c936a2da8696e77d8f986700f91058070479b7f2bbe9a67b0bb6b0e04f7ab5']}


def digest(raw: str) -> str:
    return hashlib.sha256(raw.replace('\r\n', '\n').encode('utf-8')).hexdigest()


def validate_source(source: Path, previous: str, revision: str) -> None:
    def git(*args):
        return command('git', '-C', str(source), *args)
    require(previous == BASE, 'exact_installed_branding_baseline_required')
    require(git('rev-parse', 'HEAD') == revision and not git('status', '--porcelain', '--untracked-files=all'),
            'clean_exact_branding_source_required')
    git('merge-base', '--is-ancestor', previous, revision)
    paths = set(git('diff', '--name-only', previous, revision, '--',
                    *COMPATIBILITY_PATHS, *ADDITIONAL_CONTRACT_PATHS).splitlines())
    require(paths <= set(REVIEWED_FILES) | {ROUTE_ALLOWLIST}, 'unreviewed_branding_persistent_source')
    for path, (before, after) in REVIEWED_FILES.items():
        old = git('show', f'{previous}:{path}') if before is not None else ''
        candidate = source / path
        require(candidate.is_file() and not candidate.is_symlink(), 'regular_branding_contract_file_required')
        require((before is None or digest(old + '\n') == before)
                and digest(candidate.read_text('utf-8')) == after, 'reviewed_branding_source_changed')
    validate_route_allowlist(source)
    manifest = json.loads((source / 'backend/app/core/config/release_manifest.json').read_text())
    require(manifest['schema_revision'] == TARGET, 'exact_branding_target_required')
    source_contract(source)
    for path in git('diff', '--name-only', previous, revision, '--', 'backend/app').splitlines():
        if not path.endswith('.py'):
            continue
        old = git('show', f'{previous}:{path}') if git('ls-tree', '--name-only', previous, '--', path) else ''
        new = (source / path).read_text('utf-8') if (source / path).exists() else ''
        if path == 'backend/app/infrastructure/whatsapp/tasks.py':
            # Existing queued payloads omit this optional keyword and retain
            # their previous behavior. No task name, queue or retry changes.
            declaration = '    group_invite_link: str | None = None,'
            require(old.count(declaration) == 1, 'original_broadcast_signature_changed')
            old = old.replace(declaration, declaration + '\n    include_previous_recipients: bool = False,')
        require(task_contract(old) == task_contract(new), 'unreviewed_branding_task_contract')
