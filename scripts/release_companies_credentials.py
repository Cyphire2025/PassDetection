"""Retain existing migration credentials; never provision identities or grants.

Credential work is constant-size (16 KiB custody, 2 MiB Compose output). The
read-only preflight examines catalog ACLs only, before release worker quiescence.
The fenced migration helper independently enforces the exact ownership guard.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import stat
import subprocess
from pathlib import Path
from typing import Any, Protocol, cast

from mcp_direct_release import bound_original
from mcp_direct_state import ROOT
from qa.bounded_qualification_output import capture
from release_code_update import environment
from release_retained_update import require

CREDENTIAL_FILE = 'existing-migration-credentials.private.json'
MAXIMUM_BYTES = 16384
KEYS = frozenset({'POSTGRES_USER', 'POSTGRES_PASSWORD', 'POSTGRES_DB'})


class CredentialRelease(Protocol):
    directory: Path
    source: Path
    revision: str
    record: dict[str, Any]

    def event(self, phase: str, **values: Any) -> None: ...


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def database_endpoint(backend: dict[str, Any], database: dict[str, Any]) -> dict[str, str]:
    """Use the inspected original PostgreSQL endpoint, never a Compose DNS alias."""
    networks = backend['NetworkSettings']['Networks'].keys() & database['NetworkSettings']['Networks'].keys()
    require(len(networks) == 1, 'database_network_binding_ambiguous')
    host = str(ipaddress.ip_address(database['NetworkSettings']['Networks'][next(iter(networks))]['IPAddress']))
    name = environment(database).get('POSTGRES_DB')
    require(isinstance(name, str) and bool(name), 'database_name_binding_missing')
    return {'POSTGRES_HOST': host, 'POSTGRES_PORT': '5432', 'POSTGRES_DB': str(name)}


def existing_credentials(release: CredentialRelease) -> dict[str, str]:
    """Resolve only the retained root maintenance service; do not run Compose up."""
    try:
        raw = capture(['docker', 'compose', '--project-directory', str(ROOT), '--env-file', str(ROOT / '.env'),
                       '-f', str(ROOT / 'docker-compose.yml'), '-f', str(ROOT / 'docker-compose.prod.yml'),
                       '--profile', 'maintenance', 'config', '--format', 'json'], timeout=30)
        selected = json.loads(raw)['services']['database-migrate']['environment']
        values = {key: selected[key] for key in KEYS}
    except (ValueError, KeyError, TypeError, OSError):
        raise ValueError('existing_migration_credentials_unavailable') from None
    require(all(isinstance(value, str) and 0 < len(value.encode()) <= 4096 and '\x00' not in value
                for value in values.values()), 'existing_migration_credentials_invalid')
    live = release.record['live']
    bootstrap, runtime = environment(live['db']), environment(live['backend'])
    require(all(values['POSTGRES_DB'] == item.get('POSTGRES_DB') for item in (bootstrap, runtime)),
            'migration_database_binding_changed')
    for key in ('POSTGRES_USER', 'POSTGRES_PASSWORD'):
        require(all(isinstance(item.get(key), str) and bool(item[key]) for item in (bootstrap, runtime))
                and len({values[key], bootstrap[key], runtime[key]}) == 3, 'migration_identity_must_be_distinct')
    return cast(dict[str, str], values)


def source_binding(release: CredentialRelease) -> dict[str, str]:
    live = release.record['live']
    current = bound_original(live['db'])
    bound_original(live['backend'])
    require(current['NetworkSettings']['Networks'] == live['db']['NetworkSettings']['Networks'],
            'migration_database_endpoint_changed')
    return {'revision': release.revision, 'source': str(release.source),
            'backend_id': live['backend']['Id'], 'database_id': live['db']['Id'],
            'endpoint_sha256': digest(database_endpoint(live['backend'], current))}


def read_private(path: Path) -> bytes:
    require(not path.is_symlink(), 'migration_credentials_file_invalid')
    with os.fdopen(os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)), 'rb') as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and 0 < info.st_size <= MAXIMUM_BYTES,
                'migration_credentials_file_invalid')
        if os.name == 'posix':
            require(info.st_uid == getattr(os, 'geteuid', lambda: -1)() and not (info.st_mode & 0o077),
                    'migration_credentials_file_permissions')
        raw = stream.read(MAXIMUM_BYTES + 1)
        require(len(raw) <= MAXIMUM_BYTES, 'migration_credentials_file_invalid')
        return raw


def verify_migration_credentials(release: CredentialRelease) -> dict[str, str]:
    receipt = release.record.get('migration_credentials')
    require(isinstance(receipt, dict) and receipt.get('file') == CREDENTIAL_FILE,
            'retained_migration_credentials_required')
    receipt = cast(dict[str, Any], receipt)
    require(receipt.get('binding') == source_binding(release), 'migration_credentials_source_binding_changed')
    raw = read_private(release.directory / CREDENTIAL_FILE)
    require(hashlib.sha256(raw).hexdigest() == receipt.get('sha256'), 'retained_migration_credentials_changed')
    try:
        retained = json.loads(raw)
    except ValueError:
        raise ValueError('migration_credentials_file_invalid') from None
    require(retained == existing_credentials(release), 'retained_migration_credentials_drift')
    return cast(dict[str, str], retained)


def prepare_migration_credentials(release: CredentialRelease) -> None:
    """Create once. Recovery cannot replace missing, orphaned or drifted custody."""
    if 'migration_credentials' in release.record:
        verify_migration_credentials(release)
        return
    values, binding = existing_credentials(release), source_binding(release)
    raw = (json.dumps(values, sort_keys=True) + '\n').encode()
    require(len(raw) <= MAXIMUM_BYTES, 'migration_credentials_file_invalid')
    path = release.directory / CREDENTIAL_FILE
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600), 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    release.event('existing-migration-credentials-retained', migration_credentials={
        'file': CREDENTIAL_FILE, 'sha256': hashlib.sha256(raw).hexdigest(), 'binding': binding,
    })
    verify_migration_credentials(release)


def migration_environment(release: CredentialRelease) -> dict[str, str]:
    values = verify_migration_credentials(release)
    require(release.record.get('migration_identity_preflight') == {
        'credential_binding_sha256': digest(release.record['migration_credentials']),
        'owner_verified': True, 'runtime_default_grants_verified': True,
    }, 'migration_identity_preflight_required')
    return {**database_endpoint(release.record['live']['backend'], release.record['live']['db']), **values}


# No application/settings imports, provider calls, DDL, SET ROLE or credentials in
# argv. The existing backend's driver opens one bounded, read-only connection.
PREFLIGHT = r'''
import json,sys
import psycopg2
try:
    values=json.loads(sys.stdin.buffer.read(16385))
    connection=psycopg2.connect(host=values['POSTGRES_HOST'],port=values['POSTGRES_PORT'],
        dbname=values['POSTGRES_DB'],user=values['POSTGRES_USER'],password=values['POSTGRES_PASSWORD'],
        connect_timeout=5,options='-c default_transaction_read_only=on -c statement_timeout=5000 -c lock_timeout=1000')
    with connection, connection.cursor() as cursor:
        cursor.execute("""SELECT current_user=pg_get_userbyid(d.datdba)
            AND (current_user=pg_get_userbyid(n.nspowner) OR pg_get_userbyid(n.nspowner)='pg_database_owner')
            AND NOT EXISTS(SELECT 1 FROM pg_tables WHERE schemaname='public' AND tableowner<>current_user)
            FROM pg_namespace n,pg_database d WHERE n.nspname='public' AND d.datname=current_database()""")
        owner=cursor.fetchone()[0] is True
        cursor.execute("""WITH required AS (
            SELECT a.grantee,a.privilege_type,a.is_grantable FROM pg_class c
            CROSS JOIN LATERAL aclexplode(coalesce(c.relacl,acldefault('r',c.relowner))) a
            WHERE c.oid='public.passport_submissions'::regclass AND a.grantee<>c.relowner
            AND a.privilege_type IN ('SELECT','INSERT','UPDATE','DELETE')
        ), future AS (
            SELECT a.grantee,a.privilege_type,bool_or(a.is_grantable) AS is_grantable
            FROM pg_default_acl d CROSS JOIN LATERAL aclexplode(d.defaclacl) a
            WHERE d.defaclrole=current_user::regrole AND d.defaclobjtype='r'
            AND d.defaclnamespace IN (0,'public'::regnamespace)
            GROUP BY a.grantee,a.privilege_type
        ) SELECT NOT EXISTS(SELECT * FROM required EXCEPT SELECT * FROM future),
            (SELECT count(*) FROM required WHERE grantee=%s::regrole) = 4""", (values['runtime_user'],))
        grants=all(item is True for item in cursor.fetchone())
    connection.close()
    print(json.dumps({'owner_verified':owner,'runtime_default_grants_verified':grants}))
except Exception:
    print(json.dumps({'authentication_failed':True}))
'''


def preflight_migration_credentials(release: CredentialRelease) -> None:
    values = verify_migration_credentials(release)
    backend = bound_original(release.record['live']['backend'])
    if not backend['State']['Running']:
        # Partial-migration recovery may have no running application generation.
        # It must retain the original successful preflight and exact credentials.
        migration_environment(release)
        return
    values.update(database_endpoint(release.record['live']['backend'], release.record['live']['db']))
    values['runtime_user'] = environment(backend)['POSTGRES_USER']
    raw = json.dumps(values).encode()
    require(len(raw) <= MAXIMUM_BYTES, 'migration_credentials_file_invalid')
    try:
        result = subprocess.run(['docker', 'exec', '-i', backend['Id'], 'python', '-B', '-c', PREFLIGHT],
                                input=raw, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=25, check=False)
        require(result.returncode == 0 and 0 < len(result.stdout) <= 4096, 'migration_identity_preflight_failed')
        proof = json.loads(result.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        raise ValueError('migration_identity_preflight_failed') from None
    require(proof == {'owner_verified': True, 'runtime_default_grants_verified': True},
            'existing_migration_owner_or_default_grants_required')
    release.event('migration-identity-preflight-verified', migration_identity_preflight={
        'credential_binding_sha256': digest(release.record['migration_credentials']), **proof,
    })
