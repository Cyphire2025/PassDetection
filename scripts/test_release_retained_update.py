"""Tests use fake inspected containers; never contact Docker or production."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from release_retained_update import (
    ACTIVE, APPLICATION, INFRASTRUCTURE, ROOT, SCHEMA, SERVICES, WORKERS,
    ROUTE_ALLOWLIST, RetainedUpdate, forbidden_changes, proxy_configuration, runtime_environment,
    select_live, validate_route_allowlist,
)
from release_deploy import current_main_revision, deployment_command

SHA = 'a' * 40
NEXT = 'b' * 40


def live_rows():
    rows = []
    for index, name in enumerate(sorted(SERVICES)):
        env = ['PRIVATE_SETTING=retained']
        if name in APPLICATION - {'frontend'}:
            env.extend(['APP_REVISION=' + SHA, 'EXPECTED_DATABASE_SCHEMA_REVISION=' + SCHEMA])
        if name == 'frontend': env.append('NEXT_PUBLIC_APP_REVISION=' + SHA)
        rows.append({'Id': f'{index:064x}', 'Image': 'sha256:' + 'c' * 64,
                     'Config': {'Env': env, 'Labels': {
                         'com.docker.compose.service': name, 'com.docker.compose.oneoff': 'False',
                         'com.docker.compose.project': 'retained-app' if name in ACTIVE else 'original-infra',
                         'com.docker.compose.project.working_dir': (ROOT / 'tmp/mcp-direct-old/source').as_posix() if name in ACTIVE else ROOT.as_posix()}},
                     'State': {'Running': True, 'Health': {'Status': 'healthy'}},
                     'NetworkSettings': {'Networks': {'private': {'Aliases': ['old-' + name]}}}})
    return rows


class Contracts(unittest.TestCase):
    def test_current_main_lookup_requires_one_exact_branch_identity(self):
        with patch('release_deploy.subprocess.check_output', return_value=SHA + '\trefs/heads/main\n'):
            self.assertEqual(current_main_revision(), SHA)
        for output in ('', SHA + '\trefs/heads/develop', SHA + '\trefs/heads/main\n' + NEXT + '\trefs/heads/main'):
            with self.subTest(output=output), patch('release_deploy.subprocess.check_output', return_value=output):
                with self.assertRaises(ValueError):
                    current_main_revision()

    def test_discovery_accepts_retained_layout_without_compose_files(self):
        selected = select_live(live_rows())
        self.assertEqual(set(selected), SERVICES)

    def test_discovery_rejects_ambiguity_partial_inventory_mixed_revision_or_escape(self):
        for kind in ('duplicate', 'missing', 'revision', 'frontend', 'schema', 'project', 'escape'):
            rows = live_rows()
            backend = next(row for row in rows if row['Config']['Labels']['com.docker.compose.service'] == 'backend')
            if kind == 'duplicate': rows.append(copy.deepcopy(backend))
            if kind == 'missing': rows.pop()
            if kind == 'revision': backend['Config']['Env'][1] = 'APP_REVISION=' + NEXT
            if kind == 'frontend':
                next(row for row in rows if row['Config']['Labels']['com.docker.compose.service'] == 'frontend')['Config']['Env'][-1] = 'NEXT_PUBLIC_APP_REVISION=' + NEXT
            if kind == 'schema': backend['Config']['Env'][-1] = 'EXPECTED_DATABASE_SCHEMA_REVISION=0128_mcp_document_delivery'
            if kind == 'project': backend['Config']['Labels']['com.docker.compose.project'] = 'other'
            if kind == 'escape': backend['Config']['Labels']['com.docker.compose.project.working_dir'] = str(ROOT / 'tmp/../../evil')
            with self.subTest(kind=kind), self.assertRaises(ValueError): select_live(rows)

    def test_full_dependency_changes_do_not_authorize_persistence_or_config_changes(self):
        build = ['backend/requirements.lock', 'frontend/package-lock.json', 'frontend/Dockerfile']
        persistence = ['backend/alembic/versions/new.py', 'backend/app/infrastructure/database/models.py',
                       'backend/app/core/config/release_manifest.json', 'nginx/nginx.conf', 'docker-compose.yml']
        self.assertEqual(forbidden_changes(build + persistence, 'full'), persistence)
        self.assertEqual(forbidden_changes(build + persistence, 'fast'), build + persistence)

    def test_route_allowlist_exception_needs_exact_frontend_and_page_contract(self):
        self.assertEqual(forbidden_changes([ROUTE_ALLOWLIST], 'full'), [ROUTE_ALLOWLIST])
        self.assertEqual(forbidden_changes([ROUTE_ALLOWLIST], 'fast', route_allowlist_validated=True), [ROUTE_ALLOWLIST])
        self.assertEqual(forbidden_changes([ROUTE_ALLOWLIST], 'full', route_allowlist_validated=True), [])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backend, frontend = root / ROUTE_ALLOWLIST, root / 'frontend/lib/observability/route-templates.json'
            backend.parent.mkdir(parents=True); frontend.parent.mkdir(parents=True)
            page = root / 'frontend/app/(dashboard)/groups/[groupId]/page.tsx'
            page.parent.mkdir(parents=True); page.write_text('')
            data = ['unknown', '/groups/[groupId]']
            backend.write_text(json.dumps(data)); frontend.write_text(json.dumps(data))
            validate_route_allowlist(root)
            for bad in (data + ['/groups/private-customer-value'], ['unknown', '/groups/[groupId]?token=x'], data + data):
                backend.write_text(json.dumps(bad)); frontend.write_text(json.dumps(bad))
                with self.subTest(value=bad), self.assertRaises(ValueError): validate_route_allowlist(root)
            backend.write_text(json.dumps(data)); frontend.write_text(json.dumps(['unknown']))
            with self.assertRaisesRegex(ValueError, 'route_allowlists_differ'): validate_route_allowlist(root)

    def test_runtime_environment_preserves_every_unrelated_setting(self):
        for name, row in select_live(live_rows()).items():
            before = dict(item.split('=', 1) for item in row['Config']['Env'])
            after = runtime_environment(row, NEXT)
            self.assertEqual(after['PRIVATE_SETTING'], before['PRIVATE_SETTING'])
            if name == 'frontend': self.assertEqual(after['NEXT_PUBLIC_APP_REVISION'], NEXT)
            elif name in APPLICATION:
                self.assertEqual(after['APP_REVISION'], NEXT)
                self.assertEqual(after['EXPECTED_DATABASE_SCHEMA_REVISION'], SCHEMA)

    def test_proxy_requires_upstreams_actually_bound_to_live_services(self):
        value = 'http { upstream backend { server old-backend:8000; keepalive 128; }\nupstream frontend { server old-frontend:3000; } }'
        selected = select_live(live_rows())
        result = proxy_configuration(value, selected, 'new-project')
        self.assertEqual(result.replace('new-project-', 'old-'), value)
        with self.assertRaises(ValueError): proxy_configuration(value.replace('old-backend', 'foreign'), selected, 'new-project')
        with self.assertRaises(ValueError): proxy_configuration(value + value, selected, 'new-project')

    def test_selector_requires_explicit_safe_mode_and_exact_revision(self):
        full = deployment_command('full', SHA, '', None)
        self.assertIn('deployment_mode=full', full)
        self.assertIn('expected_revision=' + SHA, full)
        fast = deployment_command('fast', SHA, 'root@200.97.171.206', Path('admin-key'))
        self.assertEqual(fast[-1], 'python3 -B /opt/globalconnect-release-tools/release_ci_dispatch.py --operator-fast ' + SHA)
        for mode, revision, host, key in [('fast', SHA, 'root@server;id', Path('key')),
                                          ('fast', SHA, 'root@server', None), ('full', SHA + ';id', '', None),
                                          ('automatic', SHA, '', None)]:
            with self.assertRaises(ValueError): deployment_command(mode, revision, host, key)

    def test_recovery_stops_every_candidate_before_any_original_starts(self):
        release = object.__new__(RetainedUpdate)
        original = select_live(live_rows())
        candidates = {name: {'Id': 'candidate-' + name} for name in ACTIVE}
        release.record = {'live': original, 'candidates': candidates, 'previous_revision': SHA}
        events = []
        release.event = lambda phase, **kw: events.append(phase)
        release.retention = lambda: events.append('retention')
        release.stop = lambda row: events.append('stop:' + row['Id'])
        release.fence_candidate = release.stop
        release.start = lambda row: events.append('start:' + row['Id'])
        release.proof = lambda *args, **kwargs: events.append('proof')
        release.rows = lambda: list(original.values())
        with patch('release_retained_update.bound_original', side_effect=lambda row: row): release.recover()
        last_stop = max(i for i, event in enumerate(events) if event.startswith('stop:'))
        first_start = min(i for i, event in enumerate(events) if event.startswith('start:'))
        self.assertLess(last_stop, first_start)
        self.assertEqual(events[-1], 'recovered-originals')
        self.assertEqual({event.removeprefix('stop:') for event in events if event.startswith('stop:')},
                         {row['Id'] for row in candidates.values()})

    def test_failed_candidate_drain_never_starts_original_writers(self):
        release = object.__new__(RetainedUpdate)
        release.record = {'live': select_live(live_rows()), 'candidates': {'backend': {'Id': 'busy'}}, 'previous_revision': SHA}
        release.event = lambda *args, **kw: None
        release.retention = lambda: None
        release.stop = lambda row: (_ for _ in ()).throw(ValueError('still_draining'))
        release.fence_candidate = release.stop
        release.start = lambda row: self.fail('must not create overlapping writers')
        with patch('release_retained_update.bound_original', side_effect=lambda row: row), self.assertRaises(ValueError):
            release.recover()

    def test_timed_out_builder_blocks_recovery_resource_overlap(self):
        release = object.__new__(RetainedUpdate)
        release.record = {'live': select_live(live_rows()), 'previous_revision': SHA}
        release.event = lambda *args, **kw: None
        release.retention = lambda: None
        release.rows = lambda: [{'Id': 'still-running-builder'}]
        release.start = lambda row: self.fail('must not overcommit alongside the builder')
        with self.assertRaisesRegex(ValueError, 'unexpected_running_container'):
            release.recover()

    def test_cutover_failure_recovers_without_overlapping_application_sets(self):
        for failure in ('before-start', 'app-proof', 'public-proof'):
            release = object.__new__(RetainedUpdate)
            live = select_live(live_rows())
            candidates = {name: {**copy.deepcopy(live[name]), 'Id': 'candidate-' + name} for name in ACTIVE}
            release.record = {'live': live, 'candidates': candidates, 'previous_revision': SHA}
            release.revision = NEXT
            running = {row['Id']: row for row in live.values()}
            events = []
            release.event = lambda phase, **kw: events.append(phase)
            release.current_main = lambda: None
            release.retention = lambda: None
            release.rows = lambda: list(running.values())
            release.schema = lambda: SCHEMA
            release.stop = lambda row: running.pop(row['Id'], None)
            release.fence_candidate = release.stop
            def start(row):
                if row['Id'].startswith('candidate-'):
                    self.assertFalse({live[name]['Id'] for name in ACTIVE} & running.keys())
                    if failure == 'before-start': raise ValueError('injected')
                else:
                    self.assertFalse({item['Id'] for item in candidates.values()} & running.keys())
                running[row['Id']] = row
            release.start = start
            def proof(rows, revision, *, public):
                if revision == NEXT and (failure == 'app-proof' and not public or failure == 'public-proof' and public):
                    raise ValueError('injected')
            release.proof = proof
            with self.subTest(failure=failure), patch('release_retained_update.bound_original', side_effect=lambda row: row):
                with self.assertRaisesRegex(ValueError, 'injected'): release.transition(candidates)
                self.assertEqual(set(running), {row['Id'] for row in live.values()})
                self.assertEqual(events[-1], 'recovered-originals')

    def test_failed_or_oom_candidate_is_fenced_without_requiring_clean_exit(self):
        for state in ({'Running': False, 'ExitCode': 1, 'OOMKilled': False},
                      {'Running': False, 'ExitCode': 137, 'OOMKilled': True}):
            release = object.__new__(RetainedUpdate)
            release.record = {}
            release.event = lambda *args, **kw: None
            row = {'Id': 'failed-candidate', 'State': state}
            with self.subTest(state=state), patch('release_retained_update.bound_original', return_value=row):
                # No Docker stop is necessary, and the original error is retained.
                release.fence_candidate(row)
            self.assertEqual(release.record['recovery_candidate_states']['failed-candidate'], state)


if __name__ == '__main__': unittest.main()
