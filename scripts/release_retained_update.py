"""Same-schema app release over inspected containers, retaining every prior resource.

Full mode consumes verified CI images. Fast mode builds source on the VPS and
explicitly has lower assurance. Neither path runs migrations or deletes data,
containers, images, volumes, builders or release evidence. A bounded ingress
pause is expected; this is not a zero-downtime deployment.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import subprocess
import sys
import time
import uuid

sys.dont_write_bytecode = True

from mcp_direct_activate import clean_stop
from mcp_direct_build import GIB, RetainedBuild, command, contract_digest
from mcp_direct_containers import LocalDocker, clone_payload
from mcp_direct_release import bound_original, require_idle
from mcp_direct_state import APPLICATION, INFRASTRUCTURE, WORKERS, fingerprint, private_json
from release_artifacts import verify_manifest
from release_code_update import COMPATIBILITY_PATHS, environment, task_contract, validate_readiness
from release_manifest import load_release_manifest
from release_traveller_whatsapp import release_lock

ROOT = Path('/opt/GlobalConnectsDashboard')
SCHEMA = '0129_travel_tracker'
REVISION = re.compile(r'[a-f0-9]{40}')
ACTIVE = APPLICATION | {'nginx'}
SERVICES = ACTIVE | INFRASTRUCTURE
ORIGIN = 'https://tech.gctravels.com'
# Full CI may qualify dependency/build changes. Persistent state, configuration,
# schema, storage and queued task contracts remain independently frozen.
FULL_BUILD_PATHS = ('backend/Dockerfile', 'frontend/Dockerfile',
                    'backend/requirements', 'frontend/package', 'frontend/tooling/',
                    'frontend/scripts/', 'backend/docker/', 'frontend/next.config.',
                    'backend/.dockerignore', 'frontend/.dockerignore', '.dockerignore')
ADDITIONAL_CONTRACT_PATHS = ('frontend/tooling', 'frontend/scripts', 'backend/docker',
                             'frontend/next.config.*', 'backend/gunicorn.conf.py',
                             '.dockerignore', 'backend/.dockerignore', 'frontend/.dockerignore')
ROUTE_ALLOWLIST = 'backend/app/core/config/frontend_route_templates.json'


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def select_live(rows: list[dict], root: Path = ROOT) -> dict[str, dict]:
    root = PurePosixPath(root.as_posix())
    selected = {}
    for row in rows:
        labels = row.get('Config', {}).get('Labels') or {}
        name = labels.get('com.docker.compose.service')
        require(name in SERVICES and name not in selected, 'ambiguous_running_service_inventory')
        require(row.get('State', {}).get('Running') is True, 'live_service_not_running')
        work = PurePosixPath(labels.get('com.docker.compose.project.working_dir', ''))
        require(work.is_absolute() and '..' not in work.parts and (work == root or work.is_relative_to(root / 'tmp')),
                'live_working_directory_outside_root')
        require(labels.get('com.docker.compose.oneoff') == 'False', 'unexpected_oneoff_service')
        selected[name] = row
    require(set(selected) == SERVICES, 'exact_live_service_inventory_required')
    app_projects = {selected[name]['Config']['Labels'].get('com.docker.compose.project') for name in ACTIVE}
    require(len(app_projects) == 1 and None not in app_projects, 'mixed_live_application_projects')
    revisions = {environment(selected[name]).get('APP_REVISION') for name in APPLICATION - {'frontend'}}
    require(len(revisions) == 1 and REVISION.fullmatch(next(iter(revisions)) or '') is not None,
            'mixed_live_application_revisions')
    require(environment(selected['frontend']).get('NEXT_PUBLIC_APP_REVISION') == next(iter(revisions)),
            'mixed_live_frontend_revision')
    require(all(environment(selected[name]).get('EXPECTED_DATABASE_SCHEMA_REVISION') == SCHEMA
                for name in APPLICATION - {'frontend'}), 'live_schema_environment_changed')
    return selected


def forbidden_changes(paths: list[str], mode: str, *, route_allowlist_validated: bool = False) -> list[str]:
    require(mode in {'full', 'fast'}, 'explicit_release_mode_required')
    return [path for path in paths if mode == 'fast' or not (
        path.startswith(FULL_BUILD_PATHS) or path == ROUTE_ALLOWLIST and route_allowlist_validated)]


def validate_route_allowlist(source: Path) -> None:
    backend = json.loads((source / ROUTE_ALLOWLIST).read_text())
    frontend = json.loads((source / 'frontend/lib/observability/route-templates.json').read_text())
    require(isinstance(backend, list) and backend == frontend and all(isinstance(item, str) for item in backend),
            'route_allowlists_differ')
    require(len(backend) == len(set(backend)) and len(backend) <= 1000, 'route_allowlist_budget_or_duplicates')
    # Derive the contract from actual App Router pages. Dynamic values must be
    # bracketed placeholders; no URL/query/body values can enter this allowlist.
    expected = {'unknown'}
    app = source / 'frontend/app'
    for page in app.rglob('page.tsx'):
        segments = [part for part in page.relative_to(app).parts[:-1]
                    if not (part.startswith('(') and part.endswith(')'))]
        require(all(re.fullmatch(r'(?:[a-z][a-z0-9-]*|\[[A-Za-z][A-Za-z0-9]*\])', part)
                    for part in segments), 'unreviewed_route_template_grammar')
        expected.add('/' + '/'.join(segments))
    require(set(backend) == expected, 'route_allowlist_must_match_actual_pages')


def runtime_environment(original: dict, revision: str) -> dict[str, str]:
    result = environment(original)
    service = original['Config']['Labels']['com.docker.compose.service']
    if service == 'frontend':
        result['NEXT_PUBLIC_APP_REVISION'] = revision
    elif service != 'nginx':
        result.update(APP_REVISION=revision, EXPECTED_DATABASE_SCHEMA_REVISION=SCHEMA)
    return result


def proxy_configuration(config: str, active: dict, project: str) -> str:
    for service, port in (('backend', 8000), ('frontend', 3000)):
        aliases = {alias for network in active[service]['NetworkSettings']['Networks'].values()
                   for alias in network.get('Aliases') or []}
        pattern = rf'(upstream\s+{service}\s*\{{\s*server\s+)([a-z0-9_-]+)(:{port};)'
        matches = list(re.finditer(pattern, config))
        require(len(matches) == 1 and matches[0].group(2) in aliases, 'proxy_upstream_binding_changed')
        config = re.sub(pattern, lambda m: m[1] + project + '-' + service + m[3], config)
    return config


class FastBuild(RetainedBuild):
    """Code-only build: dependencies are inherited and must be unchanged."""
    def backend(self, base_image: str) -> dict:
        expected = contract_digest((self.source / 'backend/contracts/api.openapi.json').read_bytes())
        code = """
import hashlib,json,pathlib,shutil,subprocess
for name in ('app','alembic','scripts'):
 target=pathlib.Path('/app')/name
 if target.exists():shutil.rmtree(target)
 shutil.copytree(pathlib.Path('/candidate')/name,target)
for name in ('alembic.ini','gunicorn.conf.py'):
 shutil.copyfile(pathlib.Path('/candidate')/name,pathlib.Path('/app')/name)
subprocess.run(['/bin/chown','-R','1001:1001','/app'],check=True)
from scripts.export_api_contract import application_contract
raw=(json.dumps(application_contract(),ensure_ascii=False,sort_keys=True,indent=2)+'\\n').encode()
assert hashlib.sha256(raw).hexdigest()==EXPECTED
""".replace('EXPECTED', repr(expected))
        identifier = self.create('backend', base_image, GIB, '/opt/venv/bin/python',
                                 ['-c', code], {'PYTHONPATH': '/opt/mcp-deps:/app'})
        self.run('docker', 'cp', str(self.source / 'backend'), f'{identifier}:/candidate', timeout=180)
        result = self.execute(identifier, 'backend', GIB)
        return {**result, 'image_id': self.commit_runtime(identifier, 'backend'), 'base_image_id': base_image}


class RetainedUpdate:
    def __init__(self, source: Path, revision: str, mode: str, artifact: Path | None = None):
        require(REVISION.fullmatch(revision) is not None and mode in {'full', 'fast'}, 'invalid_release_selection')
        require(source.resolve() == source and source.is_relative_to(ROOT / 'tmp')
                and source.parent.name.startswith('mcp-direct-') and source.name == 'source', 'invalid_release_source')
        require((mode == 'full') == (artifact is not None), 'full_requires_manifest_fast_forbids_manifest')
        self.source, self.revision, self.mode, self.artifact = source, revision, mode, artifact
        self.directory = source.parent
        self.client = LocalDocker()
        self.record = {}
        self.project = 'retained-' + revision[:12] + '-' + uuid.uuid4().hex[:8]

    def event(self, phase: str, **values) -> None:
        self.record.update(phase=phase, **values)
        private_json(self.directory / f'{time.time_ns()}-{phase}.private.json', self.record)
        print(json.dumps({'phase': phase, 'mode': self.mode, 'revision': self.revision}), flush=True)

    def rows(self, *, all: bool = False) -> list[dict]:
        ids = command('docker', 'ps', '-aq' if all else '-q', '--no-trunc').split()
        return json.loads(command('docker', 'inspect', *ids, timeout=120)) if ids else []

    def schema(self) -> str:
        row = bound_original(self.record['live']['db'])
        return command('docker', 'exec', row['Id'], 'sh', '-c',
                       'PGPASSWORD="$POSTGRES_PASSWORD" PGOPTIONS="-c default_transaction_read_only=on" '
                       'exec psql -XAt -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" '
                       '-c "SELECT version_num FROM public.alembic_version"')

    def current_main(self) -> None:
        command('git', '-C', str(ROOT), 'fetch', 'origin', 'main', timeout=180)
        require(command('git', '-C', str(ROOT), 'rev-parse', 'origin/main') == self.revision,
                'candidate_superseded_on_main')

    def compatibility(self, previous: str) -> None:
        def git(*args): return command('git', '-C', str(self.source), *args)
        require(git('rev-parse', 'HEAD') == self.revision, 'candidate_source_revision_changed')
        require(not git('status', '--porcelain', '--untracked-files=no'), 'candidate_source_modified')
        git('merge-base', '--is-ancestor', previous, self.revision)
        paths = git('diff', '--name-only', previous, self.revision, '--',
                    *COMPATIBILITY_PATHS, *ADDITIONAL_CONTRACT_PATHS).splitlines()
        allowlist_checked = self.mode == 'full' and ROUTE_ALLOWLIST in paths
        if allowlist_checked: validate_route_allowlist(self.source)
        require(not forbidden_changes(paths, self.mode, route_allowlist_validated=allowlist_checked),
                'persistent_config_or_build_contract_requires_separate_release')
        contract = load_release_manifest(self.source / 'backend/app/core/config/release_manifest.json')
        require(contract['schema_revision'] == SCHEMA and contract['worker_nodes'] == WORKERS,
                'separate_schema_or_worker_release_required')
        # Existing additive release metadata describes the already-installed schema.
        # It is not authorization to rerun a migration. Exact migration/model/config
        # source identity above and observed live head below are both mandatory.
        for path in git('diff', '--name-only', previous, self.revision, '--', 'backend/app').splitlines():
            if path.endswith('.py'):
                old = git('show', f'{previous}:{path}') if git('ls-tree', '--name-only', previous, '--', path) else ''
                new = git('show', f'{self.revision}:{path}') if git('ls-tree', '--name-only', self.revision, '--', path) else ''
                require(task_contract(old) == task_contract(new), 'queued_task_contract_changed')

    def retention(self) -> None:
        current = {row['Id']: row for row in self.rows(all=True)}
        for identifier, original in self.record['inventory'].items():
            require(identifier in current, 'previous_container_missing')
            bound_original(original)
        require(set(self.record['images_before']) <= set(command('docker', 'image', 'ls', '-q', '--no-trunc').split()),
                'previous_image_missing')
        require(set(self.record['volumes_before']) <= set(command('docker', 'volume', 'ls', '-q').split()),
                'previous_volume_missing')
        for name in INFRASTRUCTURE:
            require(bound_original(self.record['live'][name])['State']['Running'], 'infrastructure_stopped')
        require(self.schema() == SCHEMA, 'database_schema_changed')

    def backup(self) -> None:
        db = self.record['live']['db']['Id']
        size = int(command('docker', 'exec', db, 'sh', '-c',
            'PGPASSWORD="$POSTGRES_PASSWORD" exec psql -XAt -U "$POSTGRES_USER" -d "$POSTGRES_DB" '
            '-c "SELECT pg_database_size(current_database())"'))
        require(shutil.disk_usage(self.directory).free > 2 * size + 2 * GIB, 'insufficient_backup_headroom')
        path = self.directory / 'pre-release.dump'
        with path.open('xb') as output:
            subprocess.run(['docker', 'exec', db, 'sh', '-c',
                'PGPASSWORD="$POSTGRES_PASSWORD" exec pg_dump -Fc -U "$POSTGRES_USER" -d "$POSTGRES_DB"'],
                stdout=output, stderr=subprocess.DEVNULL, check=True, timeout=600)
            output.flush(); os.fsync(output.fileno())
        with path.open('rb') as source:
            subprocess.run(['docker', 'exec', '-i', db, 'pg_restore', '--list'], stdin=source,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=120)
        self.event('backup-archive-listed', backup=str(path))

    def stop(self, row: dict) -> None:
        clean_stop(self.client.graceful_stop(row['Id'], timeout=120), row)

    def fence_candidate(self, row: dict) -> None:
        # A failed replacement can already have exited with an error or OOM.
        # Recovery requires absence of writers, not a successful candidate exit.
        current = bound_original(row)
        if current['State']['Running']:
            current = self.client.graceful_stop(row['Id'], timeout=120)
        require(not current['State']['Running'], 'candidate_still_running_blocks_recovery')
        states = self.record.setdefault('recovery_candidate_states', {})
        states[row['Id']] = current['State']
        self.event('candidate-fenced')

    def start(self, row: dict) -> None:
        # Every operation uses a retained exact ID; no name-based removal/recreate.
        current = bound_original(row)
        if not current['State']['Running']:
            self.client.start(row['Id'])

    def wait_health(self, rows: dict) -> None:
        for _ in range(120):
            current = {name: bound_original(row) for name, row in rows.items()}
            if all(row['State'].get('Running') and (
                    row['State'].get('Health', {}).get('Status') == 'healthy'
                    or name in {'frontend', 'nginx'} and not row['Config'].get('Healthcheck'))
                   for name, row in current.items()):
                return
            require(not any(row['State'].get('OOMKilled') for row in current.values()), 'candidate_oom')
            time.sleep(2)
        raise ValueError('health_checks_did_not_pass')

    def proof(self, rows: dict, revision: str, *, public: bool) -> None:
        self.wait_health(rows)
        backend = rows['backend']['Id']
        code = "import json,urllib.request; print(json.dumps(json.load(urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/ready',timeout=20))))"
        validate_readiness(json.loads(command('docker', 'exec', backend, 'python', '-c', code)), revision, full=True)
        frontend = "Promise.all(['/login','/assets/upload-samples/visa-photo.png'].map(async p=>{let r=await fetch('http://127.0.0.1:3000'+p);if(r.status!==200)throw Error('probe')})).catch(()=>process.exit(1))"
        command('docker', 'exec', rows['frontend']['Id'], 'node', '-e', frontend)
        require(environment(bound_original(rows['frontend'])).get('NEXT_PUBLIC_APP_REVISION') == revision,
                'frontend_runtime_revision_changed')
        if public:
            payload = json.loads(command('curl', '--fail', '--silent', '--show-error', '--max-time', '30',
                                         ORIGIN + '/api/v1/health/ready'))
            validate_readiness(payload, revision, full=True)
            # Bind served browser bytes, not just the container environment.
            script = """
const fs=require('fs'),path=require('path'),crypto=require('crypto');
const revision=process.argv[1],root='/app/.next/static';let found;
function walk(dir){for(const item of fs.readdirSync(dir,{withFileTypes:true})){const file=path.join(dir,item.name);
 if(item.isDirectory())walk(file);else if(!found&&file.endsWith('.js')){const raw=fs.readFileSync(file);
 if(raw.includes(Buffer.from(revision)))found={path:'/_next/static/'+path.relative(root,file),sha256:crypto.createHash('sha256').update(raw).digest('hex')};}}}
walk(root);if(!found)throw Error('revision asset absent');console.log(JSON.stringify(found));
"""
            asset = json.loads(command('docker', 'exec', rows['frontend']['Id'], 'node', '-e', script, revision))
            require(isinstance(asset.get('path'), str) and re.fullmatch(r'/_next/static/[A-Za-z0-9_./%@()!~-]+\.js', asset['path'])
                    and '..' not in asset['path'], 'invalid_frontend_revision_asset')
            raw = subprocess.check_output(['curl', '--fail', '--silent', '--show-error', '--max-time', '30', ORIGIN + asset['path']], timeout=40)
            require(hashlib.sha256(raw).hexdigest() == asset['sha256'], 'public_frontend_revision_asset_mismatch')
        self.retention()

    def stage(self, images: dict) -> dict:
        live = self.record['live']
        proxy = self.directory / 'runtime-nginx' / self.project
        proxy.mkdir(mode=0o700, parents=True)
        mounts = {entry['Destination']: entry for entry in live['nginx']['Mounts']}
        for destination, filename in (('/etc/nginx/nginx.conf', 'nginx.conf'), ('/etc/nginx/conf.d', 'conf.d')):
            mount = mounts[destination]
            origin = Path(mount['Source'])
            require(mount['Type'] == 'bind' and mount.get('RW') is False and origin.resolve() == origin
                    and origin.is_relative_to(ROOT), 'proxy_mount_contract_changed')
            if origin.is_dir():
                require(not any(item.is_symlink() for item in origin.rglob('*')), 'proxy_symlink_forbidden')
                shutil.copytree(origin, proxy / filename)
            else:
                (proxy / filename).write_text(proxy_configuration(origin.read_text(), live, self.project))
        candidates = {}
        for name in sorted(ACTIVE):
            old = live[name]
            image = old['Image'] if name == 'nginx' else images['frontend' if name == 'frontend' else 'backend']
            options = dict(name=self.project + '-' + name, image_id=image,
                           environment=runtime_environment(old, self.revision), new_project=self.project,
                           source_root=str(self.source), aliases={network: self.project + '-' + name
                                                               for network in old['NetworkSettings']['Networks']})
            if name == 'nginx':
                options['nginx_mount_overrides'] = {'/etc/nginx/nginx.conf': str(proxy / 'nginx.conf'),
                                                    '/etc/nginx/conf.d': str(proxy / 'conf.d')}
            clone_payload(old, **options)  # Reject unsafe inherited launch policy before any create.
            identifier = self.client.create_clone(old, **options)
            candidates[name] = self.client.inspect(identifier)
            self.event('candidate-created', candidates=candidates)
        return candidates

    def fast_images(self) -> dict:
        live = self.record['live']
        # Stop scheduler first, prove workers idle, then free a bounded build budget.
        self.stop(live['email-beat'])
        try:
            require_idle(live)
            for name in WORKERS: self.stop(live[name])
            builder = FastBuild(self.source, self.directory, self.revision, schema_revision=SCHEMA)
            backend = builder.backend(live['backend']['Image'])
            frontend = builder.frontend(live['frontend']['Image'], ORIGIN)
            self.event('fast-images-built', fast_build={'backend': backend, 'frontend': frontend})
            return {'backend': backend['image_id'], 'frontend': frontend['image_id']}
        finally:
            # A timed-out builder may still run. Do not overcommit or kill it.
            running = self.rows()
            require(not any(row['Id'] not in self.record['inventory'] for row in running),
                    'builder_still_running_workers_not_resumed')
            for name in (*WORKERS, 'email-beat'): self.start(live[name])

    def recover(self) -> None:
        self.event('recovering')
        self.retention()
        candidates = self.record.get('candidates', {})
        for name in ('nginx', 'email-beat', 'backend', 'frontend', *WORKERS):
            if name in candidates: self.fence_candidate(candidates[name])
        require({row['Id'] for row in self.rows()} <= {row['Id'] for row in self.record['live'].values()},
                'unexpected_running_container_blocks_recovery')
        for name in ('backend', 'frontend', *WORKERS, 'email-beat'):
            self.start(self.record['live'][name])
        self.proof({name: self.record['live'][name] for name in APPLICATION}, self.record['previous_revision'], public=False)
        self.start(self.record['live']['nginx'])
        self.proof(self.record['live'], self.record['previous_revision'], public=True)
        self.event('recovered-originals')

    def run(self) -> None:
        require(not list(self.directory.glob('*-prepared.private.json')), 'existing_attempt_requires_receipt_review')
        live = select_live(self.rows())
        previous = environment(live['backend'])['APP_REVISION']
        self.compatibility(previous)
        self.current_main()
        total = sum(row['HostConfig']['Memory'] for row in live.values())
        require(all(type(row['HostConfig']['Memory']) is int and row['HostConfig']['Memory'] > 0
                    for row in live.values()) and total + 2 * GIB <= int(command('docker', 'info', '--format', '{{.MemTotal}}')),
                'steady_capacity_exceeds_host_reserve')
        require(not Path('/proc/swaps').read_text().splitlines()[1:], 'swap_must_remain_disabled')
        self.record = {'revision': self.revision, 'mode': self.mode, 'schema': SCHEMA, 'project': self.project,
                       'source': str(self.source), 'previous_revision': previous, 'live': live,
                       'inventory': {row['Id']: row for row in self.rows(all=True)},
                       'images_before': command('docker', 'image', 'ls', '-q', '--no-trunc').split(),
                       'volumes_before': command('docker', 'volume', 'ls', '-q').split()}
        self.event('prepared')
        require(self.schema() == SCHEMA, 'same_schema_required_no_migration_permitted')
        self.proof(live, previous, public=True)
        require(shutil.disk_usage(self.directory).free >= 12 * GIB, 'insufficient_retained_image_headroom')
        if self.mode == 'full':
            manifest = verify_manifest(self.artifact, self.revision, pull=True, enforce_current_policy=True)
            require(manifest['schema'] == SCHEMA, 'signed_image_schema_mismatch')
            images = {name: entry['local_image_id'] for name, entry in manifest['images'].items()}
            self.event('signed-images-verified', image_ids=images)
        else:
            images = self.fast_images()
        self.backup()
        candidates = self.stage(images)
        self.transition(candidates)

    def transition(self, candidates: dict) -> None:
        live = self.record['live']
        self.current_main()
        try:
            self.event('cutover-starting')
            for name in ('nginx', 'email-beat', 'backend', 'frontend', *WORKERS):
                self.stop(bound_original(live[name]))
            require({row['Id'] for row in self.rows()} == {live[name]['Id'] for name in INFRASTRUCTURE},
                    'writers_not_fenced')
            require(self.schema() == SCHEMA, 'same_schema_required_before_start')
            for name in ('backend', 'frontend', *WORKERS, 'email-beat'): self.start(candidates[name])
            self.proof({name: candidates[name] for name in APPLICATION}, self.revision, public=False)
            self.start(candidates['nginx'])
            self.proof(candidates, self.revision, public=True)
            require({row['Id'] for row in self.rows()} == {row['Id'] for row in candidates.values()}
                    | {live[name]['Id'] for name in INFRASTRUCTURE}, 'unexpected_running_container')
            self.event('complete', all_prior_resources_retained=True, automatic_downgrade=False)
        except BaseException:
            try: self.recover()
            except BaseException:
                self.event('recovery-required')
                raise ValueError('recovery_required_inspect_retained_receipts') from None
            raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--mode', choices=('full', 'fast'), required=True)
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--recover-receipt', type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    release = RetainedUpdate(Path(__file__).resolve().parents[1], args.revision, args.mode, args.manifest)
    def interrupted(signum, frame):
        raise ValueError('release_interrupted')
    signal.signal(signal.SIGTERM, interrupted)
    with release_lock(ROOT / 'tmp/compose-release-lock'):
        if args.recover_receipt:
            require(args.recover_receipt.resolve().parent == release.directory and not args.recover_receipt.is_symlink(),
                    'recovery_receipt_outside_attempt')
            release.record = json.loads(args.recover_receipt.read_text())
            require(release.record.get('source') == str(release.source)
                    and release.record.get('revision') == release.revision
                    and release.record.get('mode') == release.mode, 'recovery_receipt_binding_changed')
            release.recover()
        else:
            release.run()
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        # Docker/configuration/provider errors can contain credentials. Full
        # operator receipts are private; publish only a bounded local reason.
        reason = str(error) if isinstance(error, ValueError) and re.fullmatch('[a-z_]{1,100}', str(error)) else 'release_check_failed'
        print(json.dumps({'status': 'stopped', 'reason': reason, 'error_type': type(error).__name__,
                          'automatic_retry': False, 'cleanup_performed': False}), flush=True)
        raise SystemExit(1) from None
