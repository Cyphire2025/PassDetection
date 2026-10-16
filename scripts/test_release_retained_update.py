"""Tests use fake inspected containers; never contact Docker or production."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from release_retained_update import (
    ACTIVE, APPLICATION, INFRASTRUCTURE, ROOT, SCHEMA, SERVICES, WORKERS,
    ROUTE_ALLOWLIST, FastBuild, RetainedUpdate, forbidden_changes, proxy_configuration, runtime_environment,
    select_live, validate_route_allowlist, wait_full_readiness,
)
from release_code_update import CORE_CAPABILITIES
from mcp_direct_build import BuildError
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
    def test_fast_backend_replaces_runtime_owned_sources_with_chown_only(self):
        # Model CHOWN-only Linux access on Windows too, while exercising the
        # generated builder program against real replacement files/directories.
        for app_owner in (0, 1001):
            with self.subTest(app_owner=app_owner), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                app, candidate = root / 'runtime', root / 'backend'
                app.mkdir(); candidate.mkdir()
                (candidate / 'contracts').mkdir()
                (candidate / 'contracts/api.openapi.json').write_text('{}')
                for name in ('app', 'alembic', 'scripts'):
                    (app / name).mkdir(); (candidate / name).mkdir()
                    (app / name / 'stale.py').write_text('old')
                    (candidate / name / 'replacement.py').write_text('new')
                for name in ('alembic.ini', 'gunicorn.conf.py'):
                    (app / name).write_text('old'); (candidate / name).write_text('new')
                (app / 'retained-dependency').write_text('keep')
                owners = {path: 1001 for path in app.rglob('*')}
                owners[app] = app_owner
                owners[root] = 0
                normalized = []

                def chown(args, *, check, candidate=candidate):
                    self.assertTrue(check)
                    self.assertEqual(args[0], '/bin/chown')
                    path, owner = Path(args[-1]), int(args[-2].split(':')[0])
                    self.assertTrue(path == app or path.is_relative_to(app) or path == candidate)
                    if owner == 0: normalized.append(path)
                    owners[path] = owner
                    if '-R' in args:
                        owners.update({entry: owner for entry in path.rglob('*')})

                def writable(path):
                    if owners[path] != 0: raise PermissionError(str(path))

                def remove(path):
                    writable(path.parent)
                    for entry in [path, *path.rglob('*')]: writable(entry)
                    shutil.rmtree(path)

                def copy_tree(source, target):
                    writable(target.parent)
                    shutil.copytree(source, target)
                    owners.update({entry: 0 for entry in [target, *target.rglob('*')]})

                def copy_file(source, target):
                    writable(target.parent); writable(target)
                    shutil.copyfile(source, target)

                builder = FastBuild(root, root, SHA, run=Mock())
                builder.create = Mock(return_value='a' * 64)
                builder.execute = Mock(return_value={'exit_code': 0})
                builder.commit_runtime = Mock(return_value='sha256:' + 'b' * 64)
                builder.backend('sha256:' + 'c' * 64)
                code = builder.create.call_args.args[4][1]
                staging = builder.run.call_args.args[3].split(':', 1)[1]
                code = code.replace("'/app'", repr(str(app))).replace(repr(staging), repr(str(candidate)))
                with patch.dict(sys.modules, {
                    'subprocess': SimpleNamespace(run=chown),
                    'shutil': SimpleNamespace(rmtree=remove, copytree=copy_tree, copyfile=copy_file),
                    'scripts.export_api_contract': SimpleNamespace(application_contract=lambda: {}),
                }):
                    exec(compile(code, '<fast-backend-builder>', 'exec'), {})
                self.assertEqual(set(normalized), {app, candidate, *(app / name for name in
                    ('app', 'alembic', 'scripts', 'alembic.ini', 'gunicorn.conf.py'))})
                self.assertFalse(list(app.rglob('stale.py')))
                self.assertEqual(len(list(app.rglob('replacement.py'))), 3)
                self.assertTrue(all(owners[path] == 1001 for path in [app, *app.rglob('*')]))
                self.assertEqual((app / 'retained-dependency').read_text(), 'keep')
                for name in ('alembic.ini', 'gunicorn.conf.py'):
                    self.assertEqual((app / name).read_text(), 'new')

    def test_second_fast_generation_never_reads_inherited_candidate_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source, image = root / 'source', root / 'image'
            app, inherited = image / 'app', image / 'candidate'
            source.mkdir(); image.mkdir(); app.mkdir(); inherited.mkdir()
            (inherited / 'app').mkdir()
            (inherited / 'app/stale.py').write_text('old inherited source')
            backend = source / 'backend'
            backend.mkdir(); (backend / 'contracts').mkdir()
            (backend / 'contracts/api.openapi.json').write_text('{}')
            for name in ('app', 'alembic', 'scripts'):
                (backend / name).mkdir()
                (backend / name / 'current.py').write_text('current source')
            for name in ('alembic.ini', 'gunicorn.conf.py'):
                (backend / name).write_text('current config')
            stages = []
            code = None

            def create(*args):
                nonlocal code
                code = args[4][1]
                return 'a' * 64

            def docker_copy(*args, **kwargs):
                self.assertEqual(args[:2], ('docker', 'cp'))
                staging = args[3].split(':', 1)[1]
                target = image / staging.lstrip('/')
                # Reproduce Docker's existing-destination nesting semantics.
                shutil.copytree(Path(args[2]), target / 'backend' if target.exists() else target)
                stages.append(staging)

            def execute(*args):
                program = code.replace("'/app'", repr(str(app))).replace(repr(stages[-1]), repr(str(image / stages[-1].lstrip('/'))))
                with patch.dict(sys.modules, {'subprocess': SimpleNamespace(run=lambda *a, **kw: None),
                    'scripts.export_api_contract': SimpleNamespace(application_contract=dict)}):
                    exec(compile(program, '<repeated-fast-builder>', 'exec'), {})  # noqa: S102 -- exercise our generated builder program
                return {'exit_code': 0}

            builder = FastBuild(source, root, SHA, run=docker_copy)
            builder.create, builder.execute = create, execute
            builder.commit_runtime = Mock(return_value='sha256:' + 'b' * 64)
            for _ in range(2):
                builder.backend('sha256:' + 'c' * 64)
                self.assertEqual((app / 'app/current.py').read_text(), 'current source')
                self.assertFalse((app / 'app/stale.py').exists())
                self.assertFalse((image / stages[-1].lstrip('/')).exists())
            self.assertNotEqual(stages[0], stages[1])
            self.assertEqual((inherited / 'app/stale.py').read_text(), 'old inherited source')

    def test_readiness_waits_for_two_consecutive_complete_samples(self):
        ready = {'revision': SHA, 'status': 'ready', 'checks': {'database': 'ok'},
                 'capabilities': {name: {'required': True, 'available': True}
                                  for name in CORE_CAPABILITIES | {'ecr_checks'}}}
        starting = copy.deepcopy(ready)
        starting['capabilities']['ecr_checks']['available'] = False
        probe = Mock(side_effect=[BuildError('direct_build_command_failed'), starting, ready, starting, ready, ready])
        with patch('release_retained_update.time.sleep') as sleep:
            wait_full_readiness(probe, SHA)
        self.assertEqual(probe.call_count, 6)
        self.assertEqual(sleep.call_count, 5)

    def test_readiness_never_accepts_permanent_missing_required_capability(self):
        payload = {'revision': SHA, 'status': 'ready', 'checks': {'database': 'ok'},
                   'capabilities': {name: {'required': True, 'available': name != 'ecr_checks'}
                                    for name in CORE_CAPABILITIES | {'ecr_checks'}}}
        probe = Mock(return_value=payload)
        with patch('release_retained_update.time.sleep'), self.assertRaisesRegex(ValueError, 'did_not_stabilize'):
            wait_full_readiness(probe, SHA)
        self.assertEqual(probe.call_count, 12)

    def test_readiness_wrong_revision_fails_immediately(self):
        probe = Mock(return_value={'revision': NEXT})
        with patch('release_retained_update.time.sleep') as sleep, self.assertRaisesRegex(ValueError, 'revision_mismatch'):
            wait_full_readiness(probe, SHA)
        self.assertEqual(probe.call_count, 1)
        sleep.assert_not_called()

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
        self.assertEqual(forbidden_changes([ROUTE_ALLOWLIST], 'fast', route_allowlist_validated=True), [])
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
            with self.subTest(failure=failure), patch('release_retained_update.bound_original', side_effect=lambda row: row), \
                    patch('release_retained_update.wait_for_idle'):
                with self.assertRaisesRegex(ValueError, 'injected'): release.transition(candidates)
                self.assertEqual(set(running), {row['Id'] for row in live.values()})
                self.assertEqual(events[-1], 'recovered-originals')

    def test_cutover_drains_all_exact_workers_before_stopping_ingress(self):
        release, live, candidates, running, events = self.transition_fixture()
        def idle(rows):
            self.assertIs(rows, live)
            self.assertEqual(len(WORKERS), 8)
            self.assertEqual(set(running), {row['Id'] for name, row in live.items() if name != 'email-beat'})
            events.append('idle')
            return {'verified': 'all-eight-workers'}
        with patch('release_retained_update.bound_original', side_effect=lambda row: row), \
                patch('release_retained_update.wait_for_idle', side_effect=idle):
            release.transition(candidates)
        self.assertLess(events.index('stop:email-beat'), events.index('idle'))
        for name in WORKERS:
            self.assertLess(events.index('idle'), events.index('stop:' + name))
            self.assertLess(events.index('stop:' + name), events.index('stop:nginx'))
        self.assertLess(events.index('stop:nginx'), events.index('stop:backend'))
        self.assertLess(events.index('stop:frontend'), events.index('start:candidate-backend'))
        self.assertEqual(set(running), {row['Id'] for row in candidates.values()}
                         | {live[name]['Id'] for name in INFRASTRUCTURE})
        self.assertEqual(events[-1], 'complete')

    def test_busy_or_uninspectable_worker_keeps_website_up_and_starts_no_candidate(self):
        for reason in ('workers_busy_wait_before_build', 'worker_idle_evidence_unavailable'):
            release, live, candidates, running, events = self.transition_fixture()
            with self.subTest(reason=reason), patch('release_retained_update.bound_original', side_effect=lambda row: row), \
                    patch('release_retained_update.wait_for_idle', side_effect=BuildError(reason)):
                with self.assertRaisesRegex(BuildError, reason):
                    release.transition(candidates)
            self.assertEqual(set(running), {row['Id'] for row in live.values()})
            self.assertEqual(events[-1], 'recovered-originals')
            self.assertFalse(any('start:candidate-' in event for event in events))
            self.assertFalse(any('stop:' + name in events for name in ('nginx', 'backend', 'frontend', *WORKERS)))

    def test_worker_warm_shutdown_timeout_after_idle_preserves_ingress_and_recovers_stopped_workers(self):
        release, live, candidates, running, events = self.transition_fixture()
        normal_stop = release.stop
        blocked = list(WORKERS)[1]
        def stop(row):
            if row['Id'] == live[blocked]['Id']:
                events.append('blocked:' + blocked)
                raise BuildError('container_still_running_after_graceful_stop')
            normal_stop(row)
        release.stop = stop
        with patch('release_retained_update.bound_original', side_effect=lambda row: row), \
                patch('release_retained_update.wait_for_idle'):
            with self.assertRaisesRegex(BuildError, 'still_running_after_graceful_stop'):
                release.transition(candidates)
        self.assertEqual(set(running), {row['Id'] for row in live.values()})
        self.assertIn('stop:' + next(iter(WORKERS)), events)
        self.assertIn('blocked:' + blocked, events)
        self.assertFalse(any('stop:' + name in events for name in ('nginx', 'backend', 'frontend')))
        self.assertFalse(any('start:candidate-' in event for event in events))
        self.assertEqual(events[-1], 'recovered-originals')

    def transition_fixture(self):
        release = object.__new__(RetainedUpdate)
        live = select_live(live_rows())
        candidates = {name: {**copy.deepcopy(live[name]), 'Id': 'candidate-' + name} for name in ACTIVE}
        release.record = {'live': live, 'candidates': candidates, 'previous_revision': SHA}
        release.revision = NEXT
        running = {row['Id']: row for row in live.values()}
        names = {row['Id']: name for name, row in live.items()}
        events = []
        release.event = lambda phase, **kw: events.append(phase)
        release.current_main = lambda: None
        release.retention = lambda: events.append('retention')
        release.rows = lambda: list(running.values())
        release.schema = lambda: SCHEMA
        release.proof = lambda *args, **kwargs: events.append('proof')
        def stop(row):
            events.append('stop:' + names.get(row['Id'], row['Id']))
            running.pop(row['Id'], None)
        def start(row):
            candidate = row['Id'].startswith('candidate-')
            other_set = {live[name]['Id'] for name in ACTIVE} if candidate else {item['Id'] for item in candidates.values()}
            self.assertFalse(other_set & running.keys(), 'application generations must never overlap')
            events.append('start:' + names.get(row['Id'], row['Id']))
            running[row['Id']] = row
        release.stop = stop
        release.fence_candidate = stop
        release.start = start
        return release, live, candidates, running, events

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
