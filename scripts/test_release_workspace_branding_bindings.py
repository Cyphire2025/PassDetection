"""Exact release bindings reject corrupt data and unreviewed persistent sources."""
from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from release_workspace_branding_bindings import load_bindings

ROOT = Path(__file__).resolve().parents[1]
HASH = 'a' * 64


class BrandingBindingLoaderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / 'bindings.json'
        self.row = {'path': 'backend/model.py', 'before_0140': None,
                    'before_0141': 'b' * 64, 'after': HASH}

    def load(self, data, count=1):
        raw = json.dumps(data).encode('utf-8')
        self.path.write_bytes(raw)
        return load_bindings(self.path, hashlib.sha256(raw).hexdigest(), count)

    def data(self, row=None):
        return {'schema_version': 1, 'files': [self.row if row is None else row]}

    def test_exact_valid_data_preserves_public_mapping_shape_and_null_baseline(self):
        reviewed, previous = self.load(self.data())
        self.assertEqual(reviewed, {'backend/model.py': [None, HASH]})
        self.assertEqual(previous, {'backend/model.py': 'b' * 64})

    def test_source_pin_is_normalized_for_git_line_endings(self):
        raw = (json.dumps(self.data(), indent=2) + '\n').encode('utf-8')
        self.path.write_bytes(raw.replace(b'\n', b'\r\n'))
        reviewed, _ = load_bindings(self.path, hashlib.sha256(raw).hexdigest(), 1)
        self.assertEqual(reviewed['backend/model.py'][1], HASH)

    def test_changed_bytes_fail_without_repinning(self):
        self.path.write_text(json.dumps(self.data()), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'reviewed_branding_bindings_changed'):
            load_bindings(self.path, '0' * 64, 1)

    def test_missing_directory_or_symlink_manifest_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'regular_branding_bindings'):
            load_bindings(self.path, HASH, 1)
        with self.assertRaisesRegex(ValueError, 'regular_branding_bindings'):
            load_bindings(self.path.parent, HASH, 1)
        self.path.write_text('{}', encoding='utf-8')
        with (
            patch.object(Path, 'is_symlink', return_value=True),
            self.assertRaisesRegex(ValueError, 'regular_branding_bindings'),
        ):
            load_bindings(self.path, HASH, 1)

    def test_oversize_manifest_is_rejected_before_parsing(self):
        self.path.write_bytes(b' ' * (256 * 1024 + 1))
        with self.assertRaisesRegex(ValueError, 'branding_bindings_too_large'):
            load_bindings(self.path, HASH, 1)

    def test_schema_shape_version_and_exact_count_are_required(self):
        for data in [[], {}, {**self.data(), 'extra': True},
                     {**self.data(), 'schema_version': True},
                     {**self.data(), 'schema_version': 2},
                     {**self.data(), 'files': {}}, self.data()]:
            with self.subTest(data=data), self.assertRaisesRegex(ValueError, 'invalid_branding_bindings_schema'):
                self.load(data, count=2)

    def test_duplicate_json_object_keys_are_rejected_even_with_a_matching_pin(self):
        raw = b'{"schema_version":1,"schema_version":1,"files":[]}'
        self.path.write_bytes(raw)
        with self.assertRaisesRegex(ValueError, 'duplicate_branding_binding_key'):
            load_bindings(self.path, hashlib.sha256(raw).hexdigest(), 0)

    def test_only_canonical_safe_relative_source_paths_are_admitted(self):
        for name in ['', '.', '..', '../a.py', 'a/../b.py', '/a.py', 'a//b.py',
                     'a/./b.py', 'a/', 'C:/a.py', 'a\\b.py', 'a\nb.py', '\u00e9.py', 12]:
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'invalid_branding_binding_entry'):
                self.load(self.data({**self.row, 'path': name}))

    def test_duplicate_or_case_alias_source_paths_are_rejected(self):
        for name in ['backend/model.py', 'BACKEND/model.py']:
            data = self.data()
            data['files'].append({**self.row, 'path': name})
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'duplicate_branding_binding_path'):
                self.load(data, count=2)

    def test_entries_have_exact_fields_and_hashes(self):
        invalid = [None, {**self.row, 'extra': 1}, {'path': 'a.py'}]
        for row in invalid:
            data = {'schema_version': 1, 'files': [row]}
            with self.subTest(row=row), self.assertRaisesRegex(ValueError, 'invalid_branding_binding_entry'):
                self.load(data)
        for key in ['before_0140', 'before_0141', 'after']:
            for value in ['a' * 63, 'A' * 64, 'g' * 64, True, 123, {}, []]:
                with self.subTest(key=key, value=value), self.assertRaisesRegex(ValueError, 'invalid_branding_binding_digest'):
                    self.load(self.data({**self.row, key: value}))

    def test_deletion_is_not_admitted_by_a_null_after_digest(self):
        with self.assertRaisesRegex(ValueError, 'invalid_branding_binding_digest'):
            self.load(self.data({**self.row, 'after': None}))


class CurrentBindingTests(unittest.TestCase):
    def test_actual_bom_package_sources_keep_both_original_task_contracts(self):
        from release_code_update import task_contract
        from release_workspace_branding_policy import BASE, BASE_0141

        path = 'backend/app/domain/entities/__init__.py'
        current = task_contract((ROOT / path).read_text('utf-8'))
        for revision in [BASE, BASE_0141]:
            raw = subprocess.check_output(['git', 'show', f'{revision}:{path}'], cwd=ROOT)
            original = raw.decode('utf-8')
            self.assertTrue(original.startswith('\ufeff'))
            compile(raw, path, 'exec')
            self.assertEqual(task_contract(original), current)

    def test_every_before_digest_matches_the_two_immutable_git_baselines(self):
        from release_workspace_branding_policy import (
            BASE,
            BASE_0141,
            BASELINE_0141_FILES,
            REVIEWED_FILES,
            digest,
        )
        self.assertEqual(set(REVIEWED_FILES), set(BASELINE_0141_FILES))
        for name, (before, _) in REVIEWED_FILES.items():
            for revision, expected in [(BASE, before), (BASE_0141, BASELINE_0141_FILES[name])]:
                with self.subTest(path=name, revision=revision):
                    present = subprocess.check_output(
                        ['git', 'ls-tree', '--name-only', revision, '--', name], cwd=ROOT
                    ).decode('utf-8').strip()
                    if expected is None:
                        self.assertEqual(present, '')
                    else:
                        self.assertEqual(present, name)
                        raw = subprocess.check_output(['git', 'show', f'{revision}:{name}'], cwd=ROOT)
                        self.assertEqual(digest(raw.decode('utf-8')), expected)

    def test_all_prospective_persistent_changes_have_exact_admission(self):
        from release_code_update import COMPATIBILITY_PATHS
        from release_retained_update import ADDITIONAL_CONTRACT_PATHS, ROUTE_ALLOWLIST
        from release_workspace_branding_policy import BASE, BASE_0141, REVIEWED_FILES
        paths = (*COMPATIBILITY_PATHS, *ADDITIONAL_CONTRACT_PATHS)
        untracked = subprocess.check_output(
            ['git', 'ls-files', '--others', '--exclude-standard', '-z', '--', *paths], cwd=ROOT
        ).decode('utf-8').split('\0')
        for revision in [BASE, BASE_0141]:
            changed = subprocess.check_output(
                ['git', 'diff', '--name-only', '-z', revision, '--', *paths], cwd=ROOT
            ).decode('utf-8').split('\0')
            missing = set(changed + untracked) - {''} - set(REVIEWED_FILES) - {ROUTE_ALLOWLIST}
            self.assertEqual(missing, set(), f'unreviewed persistent sources relative to {revision}')


if __name__ == '__main__':
    unittest.main()
