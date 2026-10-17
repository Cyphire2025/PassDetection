"""Local synthetic Git fixtures; no SSH, Docker, production data, or provider calls."""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import release_ai_preview as module


class PreviewReleaseTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.git('init', '-q')
        self.git('config', 'user.name', 'Synthetic test')
        self.git('config', 'user.email', 'synthetic@example.test')
        self.write('frontend/proxy.ts', self.proxy_source(module.PROXY_BEFORE))
        for path in module.ROUTE_LISTS:
            self.write(path, json.dumps(['unknown']))
        (self.root / 'frontend/app').mkdir()
        self.commit()
        self.base = self.git('rev-parse', 'HEAD')
        self.patcher = patch.object(module, 'BASE_REVISION', self.base)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.write('frontend/proxy.ts', self.proxy_source(module.PROXY_AFTER))
        self.write('frontend/app/ai/page.tsx', 'export default function Page() { return null; }')
        for path in module.ROUTE_LISTS:
            self.write(path, json.dumps(['/ai', 'unknown']))
        self.commit()
        self.revision = self.git('rev-parse', 'HEAD')

    def git(self, *arguments):
        return subprocess.check_output(['git', '-C', str(self.root), *arguments], text=True,
                                       stderr=subprocess.DEVNULL).strip()

    @staticmethod
    def proxy_source(fragment):
        return 'function proxy() {\n' + fragment + '\n}'

    def write(self, path, value):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(value, encoding='utf-8')

    def commit(self):
        self.git('add', '.')
        self.git('commit', '-qm', 'synthetic fixture')

    def test_accepts_only_preview_over_the_bound_baseline(self):
        proof = module.validate_candidate(self.root, self.revision)
        self.assertEqual(proof['base_revision'], self.base)
        self.assertEqual(proof['mode'], 'fast')
        self.assertFalse(proof['full_ci_qualified'])
        self.assertFalse(proof['migrations_permitted'])

    def test_rejects_other_chat_changes_and_dependencies(self):
        for path in ('frontend/features/companies/company.tsx', 'backend/alembic/new.py', 'frontend/package.json'):
            with self.subTest(path=path):
                self.git('reset', '--hard', self.revision)
                self.write(path, 'unrelated change')
                self.commit()
                with self.assertRaisesRegex(ValueError, 'ai_only_preview_changes_permitted'):
                    module.validate_candidate(self.root, self.git('rev-parse', 'HEAD'))

    def test_rejects_broader_proxy_and_route_permissions(self):
        self.write('frontend/proxy.ts', self.proxy_source(module.PROXY_AFTER.replace('pathname === "/ai"', 'true')))
        self.commit()
        with self.assertRaisesRegex(ValueError, 'ai_proxy_must_only_enable_exact_preview_microphone'):
            module.validate_candidate(self.root, self.git('rev-parse', 'HEAD'))

    def test_rejects_additional_diagnostic_routes(self):
        for path in module.ROUTE_LISTS:
            self.write(path, json.dumps(['/ai', '/other', 'unknown']))
        self.commit()
        with self.assertRaisesRegex(ValueError, 'ai_route_allowlist_must_only_add_preview'):
            module.validate_candidate(self.root, self.git('rev-parse', 'HEAD'))

    def test_rejects_modified_checkout(self):
        self.write('frontend/proxy.ts', 'uncommitted')
        with self.assertRaisesRegex(ValueError, 'ai_candidate_source_modified'):
            module.validate_candidate(self.root, self.revision)

    def test_rejects_moved_remote_branch(self):
        release = object.__new__(module.AiPreviewRelease)
        release.source = self.root
        release.revision = self.revision
        with (
            patch.object(module, 'command', return_value='b' * 40 + '\t' + module.CANDIDATE_REF),
            self.assertRaisesRegex(ValueError, 'ai_remote_candidate_changed'),
        ):
            release.current_main()

    def test_keeps_standard_main_binding_unchanged(self):
        self.assertIsNot(module.AiPreviewRelease.current_main, module.RetainedUpdate.current_main)
        self.assertEqual(module.AiPreviewRelease.candidate_schema, module.TARGET)
        with patch.object(module.RetainedUpdate, 'compatibility') as ordinary:
            release = object.__new__(module.AiPreviewRelease)
            release.source, release.revision = self.root, self.revision
            release.compatibility(self.base)
            ordinary.assert_called_once_with(self.base)
            with self.assertRaisesRegex(ValueError, 'ai_live_baseline_changed'):
                release.compatibility('f' * 40)

    def runtime_release(self):
        release = object.__new__(module.AiPreviewRelease)
        release.mode, release.artifact = 'fast', None
        backend = {'State': {'Running': True}, 'Config': {
            'Env': ['APP_REVISION=' + self.base], 'Labels': {
                'com.docker.compose.service': 'backend', 'com.docker.compose.project': 'serving',
            },
        }}
        paused = [{'State': {'Running': False}, 'Config': {'Labels': {
            'com.docker.compose.service': name, 'com.docker.compose.project': 'serving',
            module.profile.LABEL: module.profile.PROFILE,
        }}} for name in module.profile.PAUSED]
        release.rows = Mock(return_value=[backend, *paused])
        return release, backend, paused

    def test_preserves_existing_paused_features_and_uses_ordinary_fast_runner(self):
        release, _, _ = self.runtime_release()
        with patch.object(module.RetainedUpdate, 'run') as ordinary:
            release.run()
        ordinary.assert_called_once_with()
        self.assertTrue(release.pause_email_and_photos)

    def test_refuses_if_another_chat_has_published_a_new_baseline(self):
        release, backend, _ = self.runtime_release()
        backend['Config']['Env'] = ['APP_REVISION=' + 'f' * 40]
        with (
            patch.object(module.RetainedUpdate, 'run') as ordinary,
            self.assertRaisesRegex(ValueError, 'ai_live_baseline_changed'),
        ):
            release.run()
        ordinary.assert_not_called()

    def test_refuses_to_change_an_active_feature_profile(self):
        release, _, paused = self.runtime_release()
        paused[0]['State']['Running'] = True
        with (
            patch.object(module.RetainedUpdate, 'run') as ordinary,
            self.assertRaisesRegex(ValueError, 'ai_existing_paused_profile_required'),
        ):
            release.run()
        ordinary.assert_not_called()


if __name__ == '__main__':
    unittest.main()
