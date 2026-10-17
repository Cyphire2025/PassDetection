"""Fast release of only /ai over the explicitly selected live baseline.

The ordinary main-based entrypoint is unchanged. This operator entrypoint binds
one feature branch and baseline, admits only the reviewed preview paths, and
uses the existing same-schema backup, resource, activation and recovery gates.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
from pathlib import Path

import release_pdf_checking_profile as profile
from mcp_direct_build import command
from release_code_update import environment
from release_document_distribution_contract import TARGET
from release_retained_update import (
    REVISION,
    ROOT,
    RetainedUpdate,
    require,
    validate_route_allowlist,
)
from release_traveller_whatsapp import release_lock

BASE_REVISION = '98f4fb4f7ba982fc46f917d24db63d59993a74a8'
CANDIDATE_REF = 'refs/heads/codex/ai-voice-live-base'
PROXY_BEFORE = '''  return withContentSecurityPolicy(
    NextResponse.next({ request: { headers: requestHeaders } }),
    contentSecurityPolicy,
  );'''
PROXY_AFTER = '''  const response = NextResponse.next({ request: { headers: requestHeaders } });
  if (pathname === "/ai") {
    response.headers.set("Permissions-Policy", "camera=(self), microphone=(self), geolocation=()");
  }
  return withContentSecurityPolicy(response, contentSecurityPolicy);'''
UI_PATHS = frozenset({
    'backend/app/core/config/frontend_route_templates.json',
    'frontend/app/ai/page.tsx',
    'frontend/components/ui/liquid-sculpture-hero.tsx',
    'frontend/components/ui/liquid-sculpture/engine.ts',
    'frontend/components/ui/liquid-sculpture/sculpture.module.css',
    'frontend/components/ui/liquid-sculpture/shaders.ts',
    'frontend/components/ui/liquid-sculpture/types.ts',
    'frontend/e2e/ai-voice-preview.spec.ts',
    'frontend/features/ai/components/voice-preview.module.css',
    'frontend/features/ai/components/voice-preview.tsx',
    'frontend/features/ai/hooks/use-voice-input.test.ts',
    'frontend/features/ai/hooks/use-voice-input.ts',
    'frontend/lib/observability/route-templates.json',
    'frontend/proxy.ts', 'frontend/proxy.test.ts',
    'frontend/playwright.ai.config.ts',
    'frontend/public/ai/ATTRIBUTION.md',
    'frontend/public/ai/liquid-sculpture-mobile.webp',
    'frontend/public/ai/liquid-sculpture.webp',
    'scripts/release_ai_preview.py', 'scripts/test_release_ai_preview.py',
})
ROUTE_LISTS = (
    'backend/app/core/config/frontend_route_templates.json',
    'frontend/lib/observability/route-templates.json',
)


def preview_proxy(original: str) -> str:
    require(original.count(PROXY_BEFORE) == 1, 'ai_proxy_baseline_changed')
    return original.replace(PROXY_BEFORE, PROXY_AFTER)


def validate_candidate(source: Path, revision: str) -> dict:
    """Prove the exact base and complete tracked delta before touching services."""
    require(REVISION.fullmatch(revision) is not None, 'ai_revision_invalid')

    def git(*args: str) -> str:
        return command('git', '-C', str(source), *args)

    require(git('rev-parse', 'HEAD') == revision, 'ai_candidate_checkout_changed')
    require(not git('status', '--porcelain'), 'ai_candidate_source_modified')
    git('merge-base', '--is-ancestor', BASE_REVISION, revision)
    changed = git('diff', '--name-only', BASE_REVISION, revision).splitlines()
    required = {'frontend/app/ai/page.tsx', 'frontend/proxy.ts', *ROUTE_LISTS}
    require(required <= set(changed) <= UI_PATHS, 'ai_only_preview_changes_permitted')
    original = git('show', f'{BASE_REVISION}:frontend/proxy.ts')
    candidate = git('show', f'{revision}:frontend/proxy.ts')
    require(candidate == preview_proxy(original), 'ai_proxy_must_only_enable_exact_preview_microphone')
    for path in ROUTE_LISTS:
        before = json.loads(git('show', f'{BASE_REVISION}:{path}'))
        after = json.loads(git('show', f'{revision}:{path}'))
        require('/ai' not in before and after == sorted([*before, '/ai']),
                'ai_route_allowlist_must_only_add_preview')
    validate_route_allowlist(source)
    return {'base_revision': BASE_REVISION, 'revision': revision,
            'candidate_ref': CANDIDATE_REF, 'changed_paths': changed,
            'mode': 'fast', 'full_ci_qualified': False, 'migrations_permitted': False}


class AiPreviewRelease(RetainedUpdate):
    """Retain ordinary Fast controls while binding the user's page-only branch."""
    candidate_schema = TARGET

    def current_main(self) -> None:
        # The user explicitly selected the current live baseline, not newer main.
        # Never rewrite origin/main or relax the normal main-based entrypoint.
        remote = command('git', '-C', str(ROOT), 'ls-remote', '--exit-code', 'origin', CANDIDATE_REF)
        require(remote.split() == [self.revision, CANDIDATE_REF], 'ai_remote_candidate_changed')
        validate_candidate(self.source, self.revision)

    def compatibility(self, previous: str) -> None:
        require(previous == BASE_REVISION, 'ai_live_baseline_changed')
        validate_candidate(self.source, self.revision)
        super().compatibility(previous)

    def run(self) -> None:
        require(self.mode == 'fast' and self.artifact is None, 'ai_requires_explicit_fast_mode')
        rows = self.rows(all=True)
        backends = [row for row in rows if row.get('State', {}).get('Running')
                    and row.get('Config', {}).get('Labels', {}).get('com.docker.compose.service') == 'backend']
        require(len(backends) == 1, 'ai_running_backend_ambiguous')
        backend = backends[0]
        require(environment(backend).get('APP_REVISION') == BASE_REVISION,
                'ai_live_baseline_changed')
        project = backend['Config']['Labels']['com.docker.compose.project']
        paused = [row for row in rows if row.get('Config', {}).get('Labels', {}).get('com.docker.compose.project') == project
                  and row['Config']['Labels'].get('com.docker.compose.service') in profile.PAUSED]
        require(len(paused) == len(profile.PAUSED) and all(
            not row['State']['Running'] and row['Config']['Labels'].get(profile.LABEL) == profile.PROFILE
            for row in paused), 'ai_existing_paused_profile_required')
        self.pause_email_and_photos = True
        super().run()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--recover-receipt', type=Path)
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1]
    proof = validate_candidate(source, args.revision)
    print(json.dumps(proof), flush=True)
    if not args.execute:
        require(args.recover_receipt is None, 'ai_recovery_requires_execute')
        return 0
    require(getattr(os, 'geteuid', lambda: -1)() == 0 and not os.environ.get('SSH_ORIGINAL_COMMAND'),
            'ai_requires_root_operator_session')
    os.umask(0o077)
    release = AiPreviewRelease(source, args.revision, 'fast')

    def interrupted(signum, frame):
        raise ValueError('ai_release_interrupted')

    signal.signal(signal.SIGTERM, interrupted)
    with release_lock(ROOT / 'tmp/compose-release-lock'):
        if args.recover_receipt:
            receipt = args.recover_receipt
            require(receipt.resolve().parent == release.directory and not receipt.is_symlink(),
                    'ai_recovery_receipt_outside_attempt')
            release.record = json.loads(receipt.read_text())
            require(release.record.get('source') == str(source)
                    and release.record.get('revision') == args.revision
                    and release.record.get('previous_revision') == BASE_REVISION
                    and release.record.get('mode') == 'fast'
                    and release.record.get('pause_email_and_photos') is True,
                    'ai_recovery_binding_changed')
            release.pause_email_and_photos = True
            release.project = release.record['project']
            release.current_main()
            release.recover()
        else:
            release.run()
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        reason = str(error) if isinstance(error, ValueError) and re.fullmatch('[a-z_]{1,100}', str(error)) else 'ai_release_check_failed'
        print(json.dumps({'status': 'stopped', 'reason': reason,
                          'automatic_retry': False, 'cleanup_performed': False}), flush=True)
        raise SystemExit(1) from None
