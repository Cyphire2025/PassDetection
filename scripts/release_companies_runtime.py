"""Private, capped migration helper bound to the retained PostgreSQL container."""
from __future__ import annotations

import json
import re
import subprocess
import threading
import uuid
from pathlib import Path
from typing import Any, BinaryIO, Protocol

from mcp_direct_build import GIB, admit_builder, command
from mcp_direct_containers import LocalDocker, clone_payload
from mcp_direct_memory import capture, require_zero
from mcp_direct_release import _bound_host_config, bound_original, inspect
from mcp_direct_state import fingerprint
from release_code_update import environment
from release_companies_credentials import migration_environment
from release_retained_update import require

DockerObject = dict[str, Any]


class MigrationRuntime(Protocol):
    """Small interface consumed by the isolated migration-container launcher."""
    record: DockerObject
    project: str
    source: Path
    directory: Path
    revision: str
    candidate_schema: str
    client: LocalDocker

    def verify_fence(self) -> None: ...
    def rows(self, *, all: bool = False) -> list[DockerObject]: ...
    def event(self, phase: str, **values: Any) -> None: ...


def helper_binding(row: DockerObject) -> DockerObject:
    """Journal immutable configuration digests, never the helper's credentials."""
    return {'Id': row['Id'], 'Image': row['Image'], 'configuration_sha256': fingerprint({
        'Config': row['Config'], 'HostConfig': _bound_host_config(row['HostConfig']),
        'Mounts': sorted(map(fingerprint, row['Mounts'])),
    })}


def bound_migration_helper(original: DockerObject) -> DockerObject:
    if 'configuration_sha256' not in original:
        return bound_original(original)  # Previously retained attempt format.
    current = inspect(original['Id'])
    require(helper_binding(current) == original, 'migration_helper_configuration_changed')
    return current


def database_command(database: DockerObject, arguments: tuple[str, ...], *, timeout: int,
                     stdin_file: BinaryIO | None = None, stdout_file: BinaryIO | None = None) -> str:
    row = bound_original(database)
    result = subprocess.run(
        ['docker', 'exec', '-i', row['Id'], *arguments],
        stdin=stdin_file if stdin_file is not None else subprocess.DEVNULL,
        stdout=stdout_file if stdout_file is not None else subprocess.PIPE,
        stderr=subprocess.DEVNULL, timeout=timeout, check=False,
    )
    require(result.returncode == 0 and len(result.stdout or b'') <= 1024 * 1024, 'database_maintenance_command_failed')
    return result.stdout.decode().strip() if result.stdout else ''


def helper_payload(release: MigrationRuntime, request: dict[str, Any]) -> tuple[DockerObject, str]:
    original = release.record['live']['backend']
    values = environment(original)
    values.update(request['environment'])
    # Database authority is selected last; a request cannot redirect this helper.
    values.update(migration_environment(release))
    values.update(APP_REVISION=release.revision, EXPECTED_DATABASE_SCHEMA_REVISION=release.candidate_schema,
                  APP_ENV='development', MCP_ENABLED='false', TRAVELLER_REUSE_DISCLOSURE_ENABLED='false')
    # An inherited alternate connection URL must never override inspected binding.
    for key in ('DATABASE_URL', 'SQLALCHEMY_DATABASE_URI', 'POSTGRES_DSN'):
        values.pop(key, None)
    payload = clone_payload(
        original, name=release.project + '-migration', image_id=request['image_id'],
        environment=values, new_project=release.project, source_root=str(release.source),
        aliases={network: release.project + '-migration' for network in original['NetworkSettings']['Networks']},
    )
    gate = '/tmp/companies-migration-' + uuid.uuid4().hex
    barrier = (
        'import os,signal,sys,time; signal.signal(signal.SIGTERM,lambda *_:sys.exit(0)); '
        'deadline=time.monotonic()+120\n'
        'while not os.path.exists(sys.argv[1]):\n'
        ' if time.monotonic()>deadline:sys.exit(3)\n'
        ' time.sleep(0.1)\n'
        'os.execvp(sys.argv[2],sys.argv[2:])'
    )
    arguments = list(request['arguments'])
    require(arguments[0] == 'python', 'unexpected_migration_interpreter')
    arguments.insert(1, '-B')
    payload.update(Cmd=['python', '-B', '-c', barrier, gate, *arguments], Entrypoint=[],
                   WorkingDir='/app', Healthcheck={'Test': ['NONE']})
    payload['HostConfig'].update(Memory=GIB, MemorySwap=GIB, NanoCpus=1_000_000_000,
                               PidsLimit=256, RestartPolicy={'Name': 'no', 'MaximumRetryCount': 0})
    return payload, gate


def migration_stdout(identifier: str, *, timeout: float = 30.0) -> bytes:
    """Read the complete machine stream only; O(32 KiB) memory, bounded time.

    Alembic writes human diagnostics to stderr. Combining the two streams loses
    their ordering and can turn a successful migration into a missing receipt.
    Never print or retain discarded stderr, which may include sensitive context.
    """
    output = bytearray()
    exceeded = threading.Event()
    failures: list[OSError] = []
    try:
        with subprocess.Popen(['docker', 'logs', identifier], stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as process:
            assert process.stdout is not None
            pipe = process.stdout

            def consume() -> None:
                try:
                    while chunk := pipe.read(8192):
                        remaining = 32768 - len(output)
                        output.extend(chunk[:remaining])
                        if len(chunk) > remaining:
                            exceeded.set()
                            process.kill()
                            break
                except OSError as error:
                    failures.append(error)
                    process.kill()

            reader = threading.Thread(target=consume, daemon=True)
            reader.start()
            try:
                code = process.wait(timeout=timeout)
            except BaseException:
                process.kill()
                process.wait(timeout=10)
                raise
            finally:
                reader.join(timeout=5)
            require(not exceeded.is_set(), 'migration_result_budget_exceeded')
            require(code == 0 and not reader.is_alive() and not failures, 'migration_result_read_failed')
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError('migration_result_read_failed') from None
    require(bool(output), 'migration_validation_result_missing')
    return bytes(output)


def read_migration_result(identifier: str) -> dict[str, Any]:
    try:
        # Exactly one object. Extra stdout or a second receipt fails closed.
        result = json.loads(migration_stdout(identifier).decode('utf-8'))
    except (UnicodeError, json.JSONDecodeError):
        raise ValueError('migration_validation_result_missing') from None
    require(isinstance(result, dict) and result.get('status') in {'baseline_captured', 'upgraded', 'already_at_target'}
            and isinstance(result.get('preservation_sha256'), str)
            and re.fullmatch('[a-f0-9]{64}', result['preservation_sha256']) is not None,
            'migration_validation_result_invalid')
    # Only reference-only validated machine results enter the durable journal.
    allowed = {'status', 'source_schema', 'target_schema', 'started_schema', 'executed_revisions',
               'preservation_sha256', 'release_proof_sha256', 'new_tables_empty',
               'runtime_grants_verified', 'automatic_downgrade'}
    require(set(result) <= allowed, 'unexpected_migration_result_fields')
    return dict(result)


def run_migration_helper(release: MigrationRuntime, request: dict[str, Any]) -> dict[str, Any]:
    release.verify_fence()
    payload, gate = helper_payload(release, request)
    identifier = release.client.request(
        'POST', '/containers/create?name=' + release.project + '-migration-' + uuid.uuid4().hex[:12], payload,
    )['Id']
    helper = release.client.inspect(identifier)
    helpers = [*release.record.get('migration_helpers', []), helper_binding(helper)]
    release.event('migration-helper-retained', migration_helpers=helpers, migration_proof=request['proof'])
    release.verify_fence()
    admit_builder(release.rows(), int(command('docker', 'info', '--format', '{{.MemTotal}}')), GIB)
    release.client.start(identifier)
    # The unique gate has not been created. Admission failure cannot run DDL.
    try:
        require_zero(capture({'database-migration': helper}, inspect=bound_original))
    except BaseException:
        release.client.graceful_stop(identifier, timeout=30)
        raise
    command('docker', 'exec', identifier, 'python', '-B', '-c', "import sys;open(sys.argv[1],'x').close()", gate)
    code = command('docker', 'wait', identifier, timeout=request['timeout'])
    current = bound_migration_helper(helpers[-1])
    release.event('migration-helper-exited', migration_helper_state=current['State'])
    require(code == '0' and current['State'].get('ExitCode') == 0
            and not current['State']['Running'] and not current['State'].get('OOMKilled')
            and current.get('RestartCount', 0) == 0, 'migration_failed_forward_repair_required')
    result = read_migration_result(identifier)
    release.event('migration-result-retained', migration_result=result)
    return dict(result)
