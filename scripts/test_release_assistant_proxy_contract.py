"""No Docker/SSH: prove admission cannot change any existing proxy behavior."""

import json
from pathlib import Path
import tempfile
import unittest

from release_assistant_proxy_contract import (
    ANCHOR, PROXY_PATH, VOICE_LOCATION, stage_assistant_proxy, validate_assistant_proxy,
)
from release_retained_update import ROUTE_ALLOWLIST, forbidden_changes, validate_route_allowlist


class AssistantProxyContract(unittest.TestCase):
    def setUp(self):
        self.old = 'server {\n    listen 443 ssl;\n' + ANCHOR + '        proxy_pass http://backend;\n    }\n}\n'
        self.new = self.old.replace(ANCHOR, VOICE_LOCATION + ANCHOR, 1)

    def test_only_exact_addition_receives_explicit_admission(self):
        validate_assistant_proxy(self.old, self.new)
        for mode in ('fast', 'full'):
            self.assertEqual(forbidden_changes([PROXY_PATH], mode), [PROXY_PATH])
            self.assertEqual(forbidden_changes([PROXY_PATH], mode, assistant_proxy_validated=True), [])
            self.assertEqual(forbidden_changes(['nginx/nginx.conf'], mode, assistant_proxy_validated=True), ['nginx/nginx.conf'])

    def test_other_proxy_changes_and_wrong_placement_remain_forbidden(self):
        candidates = [
            self.new.replace('listen 443 ssl;', 'listen 443;'),
            self.new.replace('location = /api/v1/ai-assistant/voice', 'location /api/v1/ai-assistant/voice'),
            self.new.replace('proxy_set_header Origin $http_origin;', 'proxy_set_header Origin https://other.test;'),
            self.new.replace('proxy_set_header Cookie $http_cookie;', ''),
            self.new.replace('proxy_pass http://backend;', 'proxy_pass http://other;', 1),
            self.new.replace('proxy_read_timeout 30s;', 'proxy_read_timeout 3000s;'),
            VOICE_LOCATION + self.old,
            self.new.replace(ANCHOR, VOICE_LOCATION + ANCHOR),
            self.old,
        ]
        for candidate in candidates:
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                validate_assistant_proxy(self.old, candidate)
        with self.assertRaises(ValueError):
            validate_assistant_proxy(self.new, self.old)
        with self.assertRaises(ValueError):
            validate_assistant_proxy(self.old + ANCHOR, self.new + ANCHOR)

    def test_intercepted_slots_have_canonical_urls_in_both_privacy_registries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for page in ('ai', '(dashboard)/@assistant/(.)ai', '(dashboard)/settings/ai'):
                path = root / 'frontend/app' / page / 'page.tsx'
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('export default function Page() {}')
            for relative in (ROUTE_ALLOWLIST, 'frontend/lib/observability/route-templates.json'):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(['/ai', '/settings/ai', 'unknown']))
            validate_route_allowlist(root)
            (root / ROUTE_ALLOWLIST).write_text(json.dumps(['/ai', '/@assistant', '/settings/ai', 'unknown']))
            with self.assertRaises(ValueError):
                validate_route_allowlist(root)

    def test_staging_adds_route_to_inherited_copy_and_preserves_operator_rules(self):
        inherited = self.old.replace('listen 443 ssl;', 'listen 443 ssl;\n    add_header X-Operator-Policy retained;')
        staged = stage_assistant_proxy(inherited, self.new)
        self.assertEqual(staged.replace(VOICE_LOCATION, '', 1), inherited)
        self.assertEqual(staged.count(VOICE_LOCATION), 1)
        self.assertEqual(stage_assistant_proxy(staged, self.new), staged)
        self.assertEqual(stage_assistant_proxy(inherited, self.old), inherited)

    def test_staging_never_accepts_a_changed_or_duplicate_voice_route(self):
        for inherited, source in [
            (self.old, self.new.replace('proxy_read_timeout 30s;', 'proxy_read_timeout 300s;')),
            (self.new.replace('proxy_set_header Cookie $http_cookie;', ''), self.new),
            (self.new + VOICE_LOCATION, self.new),
        ]:
            with self.subTest(inherited=inherited, source=source), self.assertRaises(ValueError):
                stage_assistant_proxy(inherited, source)
