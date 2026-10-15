"""Exact document release: signed Full or explicitly selected VPS Fast build."""
from __future__ import annotations

import re
import shutil
import sys
from functools import partial
from pathlib import Path
from typing import Any

import release_document_resources as resources
from mcp_direct_activate import clean_stop
from mcp_direct_build import GIB, command
from mcp_direct_release import bound_original, wait_for_idle
from mcp_direct_state import APPLICATION, WORKERS
from release_artifacts import verify_manifest
from release_code_update import environment
from release_companies_credentials import (
    migration_environment,
    preflight_migration_credentials,
    prepare_migration_credentials,
)
from release_companies_runtime import (
    bound_migration_helper,
    database_command,
    run_migration_helper,
)
from release_document_distribution_contract import CHAIN, SOURCE, TARGET
from release_document_distribution_policy import validate_additive_source
from release_mcp_contract import require_source_contract
from release_mcp_database import MCPDatabaseRelease, ReleaseBindings, digest_json
from release_retained_update import (
    ACTIVE,
    RetainedUpdate,
    require,
    select_live,
)


class DocumentRetainedUpdate(RetainedUpdate):
    candidate_schema: str = TARGET

    def __init__(self, source, revision, mode, artifact=None):
        require(mode in {'full', 'fast'} and (mode == 'full') == (artifact is not None),
                'document_release_requires_explicit_mode_binding')
        super().__init__(source, revision, mode, artifact)

    def candidate_environment(self, original: dict[str, Any]) -> dict[str, str]:
        return super().candidate_environment(original)

    def create_candidate(self, original: dict, options: dict) -> str:
        if not self.record.get('additive_release', True):
            return super().create_candidate(original, options)
        require(resources.qualification(self) == self.record['resource_qualification'],
                'retained_resource_qualification_required')
        return resources.create_app_candidate(self, original, options)

    def event(self, phase: str, **values: Any) -> None:
        super().event(phase, additive_release=getattr(self, 'additive', self.record.get('additive_release', True)), **values)

    def retention_schema(self) -> str:
        if not self.record.get('additive_release', True):
            return self.candidate_schema
        current = self.schema()
        require(current in {SOURCE, *CHAIN}, 'unexpected_schema_during_additive_release')
        return current

    def compatibility(self, previous: str) -> None:
        if self.record.get('additive_release', True):
            validate_additive_source(self.source, self.revision, previous)
            if self.mode == 'fast':
                from release_document_fast import validate_dependencies
                validate_dependencies(self.source, previous, self.revision)
        else:
            super().compatibility(previous)

    def signed_images(self) -> dict[str, str]:
        if self.artifact is None:
            raise ValueError('signed_manifest_required_for_additive_release')
        manifest = verify_manifest(self.artifact, self.revision, pull=True, enforce_current_policy=True)
        require(manifest['schema'] == TARGET, 'signed_image_schema_mismatch')
        require_source_contract(manifest, self.source)
        images = {name: entry['local_image_id'] for name, entry in manifest['images'].items()}
        require(set(images) == {'backend', 'frontend'}, 'signed_image_inventory_mismatch')
        if 'image_ids' in self.record:
            require(images == self.record['image_ids'], 'resume_image_binding_changed')
        self.event('signed-images-verified', image_ids=images)
        return images

    def candidate_images(self, *, recover: bool = False) -> dict[str, str]:
        if self.mode == 'full':
            return self.signed_images()
        from release_document_fast import binding, verify_images, verify_rehearsal
        if not recover:
            with self.background_quiescence():
                images = self.build_fast_images()
                self.event('fast-document-images-built', image_ids=images)
                self.event('fast-document-source-bound', fast_document_binding=binding(self.source, self.revision, self.record))
                verify_images(self.source, self.revision, self.record)
                self.rehearse_fast_migration()
        images = verify_images(self.source, self.revision, self.record)
        verify_rehearsal(self.directory, self.record)
        return images

    def rehearse_fast_migration(self) -> None:
        from release_document_fast import read_rehearsal
        receipt = self.directory / 'fast-document-migration-rehearsal.json'
        require(not receipt.exists() and not receipt.is_symlink(), 'existing_fast_rehearsal_requires_review')
        command(sys.executable, '-B', str(self.source / 'scripts/qa/qualify_document_migration.py'),
                '--image', self.record['image_ids']['backend'], '--revision', self.revision,
                '--postgres-image', self.record['live']['db']['Image'], '--output', str(receipt), timeout=1800)
        self.event('fast-document-migration-rehearsal-verified', fast_document_migration_rehearsal=read_rehearsal(
            receipt, self.record['fast_document_binding']))

    def verify_resource_qualification(self) -> None:
        require(resources.qualification(self) == self.record.get('resource_qualification'),
                'retained_resource_qualification_required')

    def verify_candidate_configuration(self) -> None:
        if self.mode == 'fast':
            from release_document_fast import verify_images, verify_rehearsal
            verify_images(self.source, self.revision, self.record)
            verify_rehearsal(self.directory, self.record)
        self.verify_resource_qualification()
        for name, candidate in self.record['candidates'].items():
            actual = bound_original(candidate)
            original = self.record['live'][name]
            require(environment(actual) == self.candidate_environment(original),
                    'candidate_runtime_configuration_changed')
            host = dict(original['HostConfig'])
            if name in {'worker', 'frontend'}:
                host.update(Memory=resources.LIMITS[name][1] * resources.MIB,
                            MemorySwap=resources.LIMITS[name][1] * resources.MIB)
            require(actual['HostConfig']['Memory'] == host['Memory']
                    and actual['HostConfig'].get('MemorySwap') == host.get('MemorySwap'),
                    'candidate_resource_limits_changed')

    def verify_migration_identity(self) -> None:
        preflight_migration_credentials(self)

    def assert_writer_fence(self) -> None:
        live, candidates = self.record['live'], self.record['candidates']
        require(set(candidates) == ACTIVE, 'incomplete_candidate_inventory')
        for name in ACTIVE:
            clean_stop(bound_original(live[name]), live[name])
            require(not bound_original(candidates[name])['State']['Running'], 'candidate_writer_running')
        for helper in self.record.get('migration_helpers', []):
            require(not bound_migration_helper(helper)['State']['Running'], 'migration_helper_still_running')
        permitted = {row['Id'] for row in resources.infrastructure(self).values()}
        require({row['Id'] for row in self.rows()} <= permitted,
                'unexpected_running_container_during_migration')

    def verify_fence(self) -> None:
        self.assert_writer_fence()
        infrastructure = resources.infrastructure(self)
        require({row['Id'] for row in self.rows()} == {row['Id'] for row in infrastructure.values()},
                'infrastructure_not_ready_during_migration')
        for name, original in infrastructure.items():
            current = bound_original(original)
            require(current['State']['Running'], 'infrastructure_stopped')
            if name not in resources.DATASETS:
                require(current['NetworkSettings']['Networks'] == original['NetworkSettings']['Networks'],
                        'infrastructure_network_binding_changed')
        self.retention()

    def retention(self) -> None:
        if not self.record.get('additive_release', True):
            return super().retention()
        current = {row['Id']: row for row in self.rows(all=True)}
        for identifier, original in self.record['inventory'].items():
            require(identifier in current, 'previous_container_missing')
            bound_original(original)
        require(set(self.record['images_before']) <= set(command('docker', 'image', 'ls', '-q', '--no-trunc').split()),
                'previous_image_missing')
        require(set(self.record['volumes_before']) <= set(command('docker', 'volume', 'ls', '-q').split()),
                'previous_volume_missing')
        for original in resources.infrastructure(self).values():
            require(bound_original(original)['State']['Running'], 'infrastructure_stopped')
        require(self.schema() == self.retention_schema(), 'database_schema_changed')

    def database_release(self) -> MCPDatabaseRelease:
        live = self.record['live']
        # Includes immutable inspected endpoint/credentials digest, never plaintext.
        binding = digest_json({'database': live['db'], 'connection': migration_environment(self)})
        fence = digest_json({
            'originals': {name: live[name]['Id'] for name in sorted(ACTIVE)},
            'candidates': {name: self.record['candidates'][name]['Id'] for name in sorted(ACTIVE)},
        })
        bindings = ReleaseBindings(self.revision, self.record['image_ids']['backend'], binding, fence)
        return MCPDatabaseRelease(
            self.source, self.directory, bindings,
            database_command=partial(database_command, live['db']),
            verify_fence=self.verify_fence, read_schema=self.schema,
        )

    def migrate(self) -> None:
        self.verify_candidate_configuration()
        self.verify_fence()
        database = self.database_release()
        backup = self.record.get('database_backup')
        if backup is None:
            require(self.schema() == SOURCE, 'original_source_backup_required_for_resume')
            size = int(database.command(('sh', '-c', (
                'PGPASSWORD="$POSTGRES_PASSWORD" exec psql -XAt -U "$POSTGRES_USER" -d "$POSTGRES_DB" '
                '-c "SELECT pg_database_size(current_database())"')), timeout=30))
            require(shutil.disk_usage(self.directory).free > 2 * size + 2 * GIB, 'insufficient_backup_headroom')
            backup = database.backup()
            self.event('fenced-database-backup-verified', database_backup=backup)
        request = database.migration_request(backup)
        if not self.has_verified_migration(request, backup):
            baseline = self.original_baseline(request, backup)
            request['environment']['MCP_RELEASE_BASELINE_SHA256'] = baseline
            result = run_migration_helper(self, request)
            require(result.get('status') in {'upgraded', 'already_at_target'}
                    and result.get('source_schema') == SOURCE
                    and result.get('target_schema') == TARGET
                    and result.get('release_proof_sha256') == request['environment']['MCP_RELEASE_PROOF_SHA256']
                    and result.get('preservation_sha256') == baseline
                    and result.get('new_tables_empty') is True
                    and result.get('new_columns_null') is True
                    and result.get('runtime_grants_verified') is True
                    and result.get('automatic_downgrade') is False,
                    'complete_migration_validation_required')
            database.verify_target(backup)
            self.event('database-migration-verified', schema=TARGET, database_validation={
                'backup_sha256': backup['sha256'], 'baseline_sha256': baseline,
                'release_proof_sha256': request['environment']['MCP_RELEASE_PROOF_SHA256'],
                'image_id': request['image_id'], 'target_schema': TARGET,
                'helper_id': self.record['migration_helpers'][-1]['Id'],
            })
        database.verify_target(backup)

    def original_baseline(self, request: dict[str, Any], backup: dict[str, Any]) -> str:
        baseline = self.record.get('source_preservation_baseline')
        proof = request['environment']['MCP_RELEASE_PROOF_SHA256']
        if baseline is None:
            require(self.schema() == SOURCE, 'original_preservation_baseline_required_for_resume')
            capture = {**request, 'arguments': (*request['arguments'], '--capture-baseline')}
            result = run_migration_helper(self, capture)
            baseline = {**result, 'backup_sha256': backup['sha256']}
            self.event('source-preservation-baseline-retained', source_preservation_baseline=baseline)
        require(isinstance(baseline, dict) and baseline.get('status') == 'baseline_captured'
                and baseline.get('source_schema') == SOURCE and baseline.get('target_schema') == TARGET
                and baseline.get('backup_sha256') == backup['sha256']
                and baseline.get('release_proof_sha256') == proof
                and baseline.get('automatic_downgrade') is False
                and isinstance(baseline.get('preservation_sha256'), str)
                and re.fullmatch('[a-f0-9]{64}', baseline['preservation_sha256']) is not None,
                'original_preservation_baseline_binding_changed')
        return str(baseline['preservation_sha256'])

    def has_verified_migration(self, request: dict[str, Any], backup: dict[str, Any]) -> bool:
        """A completed migration receipt permits recovery after target app writes.

        An Alembic target head or helper exit alone never creates this authority.
        The receipt is emitted only after full source-baseline/catalog/grant proof.
        """
        validation = self.record.get('database_validation')
        if validation is None:
            return False
        require(isinstance(validation, dict), 'migration_validation_receipt_invalid')
        require(request['already_at_target'], 'validated_migration_schema_changed')
        baseline = self.original_baseline(request, backup)
        helpers = [row for row in self.record.get('migration_helpers', []) if row['Id'] == validation.get('helper_id')]
        require(len(helpers) == 1 and validation == {
            'backup_sha256': backup['sha256'], 'baseline_sha256': baseline,
            'release_proof_sha256': request['environment']['MCP_RELEASE_PROOF_SHA256'],
            'image_id': request['image_id'], 'target_schema': TARGET, 'helper_id': helpers[0]['Id'],
        }, 'migration_validation_receipt_binding_changed')
        helper = bound_migration_helper(helpers[0])
        require(helper['Image'] == request['image_id'] and not helper['State']['Running']
                and helper['State'].get('ExitCode') == 0 and not helper['State'].get('OOMKilled')
                and helper.get('RestartCount', 0) == 0, 'validated_migration_helper_changed')
        return True

    def activate_candidates(self) -> None:
        require(self.schema() == TARGET, 'target_schema_required_before_candidate_start')
        self.verify_candidate_configuration()
        self.verify_fence()
        candidates = self.record['candidates']
        for name in ('backend', 'frontend', *WORKERS, 'email-beat'):
            self.start(candidates[name])
        self.proof({name: candidates[name] for name in APPLICATION}, self.revision, public=False)
        self.start(candidates['nginx'])
        self.proof(candidates, self.revision, public=True)
        require({row['Id'] for row in self.rows()} == {row['Id'] for row in candidates.values()}
                | {row['Id'] for row in resources.infrastructure(self).values()}, 'unexpected_running_container')
        self.retention()
        self.event('complete', all_prior_resources_retained=True, automatic_downgrade=False)

    def transition(self, candidates: dict[str, Any]) -> None:
        if not self.record.get('additive_release', True):
            return super().transition(candidates)
        self.current_main()
        self.verify_migration_identity()
        live = self.record['live']
        try:
            self.event('precutover-draining')
            self.stop(bound_original(live['email-beat']))
            wait_for_idle(live)
            for name in WORKERS:
                self.stop(bound_original(live[name]))
            self.event('cutover-starting')
            for name in ('nginx', 'backend', 'frontend'):
                self.stop(bound_original(live[name]))
            self.migrate()
            resources.apply(self)
            self.activate_candidates()
        except BaseException:
            # Never restart a source-schema writer after an additive revision commits.
            # A helper timeout may still mean running DDL: retain it, do not retry.
            self.hold_candidates()
            raise

    def hold_candidates(self) -> None:
        """Leave ingress and replacement writers fenced; never touch a live helper."""
        try:
            for name in ('nginx', 'email-beat', 'backend', 'frontend', *WORKERS):
                self.fence_candidate(self.record['candidates'][name])
        finally:
            self.event('forward-recovery-required', automatic_downgrade=False)

    def recover(self) -> None:
        if self.record.get('additive_release') is False:
            return super().recover()
        require(self.record.get('additive_release') is True, 'additive_recovery_receipt_required')
        require(set(self.record.get('candidates', {})) == ACTIVE, 'incomplete_candidate_inventory')
        self.project = self.record['project']
        self.current_main()
        self.compatibility(self.record['previous_revision'])
        self.candidate_images(recover=True)
        self.verify_candidate_configuration()
        # Reject live helper first, without stopping any potentially healthy app.
        for helper in self.record.get('migration_helpers', []):
            require(not bound_migration_helper(helper)['State']['Running'], 'migration_helper_still_running')
        self.verify_migration_identity()
        for name in ('nginx', 'email-beat', 'backend', 'frontend', *WORKERS):
            self.fence_candidate(self.record['candidates'][name])
        for name in ('nginx', 'email-beat', 'backend', 'frontend', *WORKERS):
            self.stop(bound_original(self.record['live'][name]))
        try:
            if self.record.get('database_validation') is not None:
                resources.apply(self)
            self.migrate()
            resources.apply(self)
            self.activate_candidates()
        except BaseException:
            self.hold_candidates()
            raise

    def run(self) -> None:
        rows = self.rows()
        backend = [row for row in rows if row['Config']['Labels'].get('com.docker.compose.service') == 'backend']
        require(len(backend) == 1, 'ambiguous_running_backend')
        current = environment(backend[0]).get('EXPECTED_DATABASE_SCHEMA_REVISION')
        require(current in {SOURCE, TARGET}, 'unsupported_live_schema_environment')
        if current == TARGET:
            self.additive = False
            self.record['additive_release'] = False
            return super().run()
        require(not list(self.directory.glob('*-prepared.private.json')), 'existing_attempt_requires_receipt_review')
        live = select_live(rows, schema=SOURCE)
        previous = environment(live['backend'])['APP_REVISION']
        self.compatibility(previous)
        self.current_main()
        total = sum(row['HostConfig']['Memory'] for row in live.values())
        require(all(type(row['HostConfig']['Memory']) is int and row['HostConfig']['Memory'] > 0 for row in live.values())
                and total + 2 * GIB <= int(command('docker', 'info', '--format', '{{.MemTotal}}')),
                'steady_capacity_exceeds_host_reserve')
        require(not Path('/proc/swaps').read_text().splitlines()[1:], 'swap_must_remain_disabled')
        self.record = {
            'revision': self.revision, 'mode': self.mode, 'schema': SOURCE, 'project': self.project,
            'source': str(self.source), 'previous_revision': previous, 'live': live, 'additive_release': True,
            'inventory': {row['Id']: row for row in self.rows(all=True)},
            'images_before': command('docker', 'image', 'ls', '-q', '--no-trunc').split(),
            'volumes_before': command('docker', 'volume', 'ls', '-q').split(),
        }
        self.event('prepared')
        require(self.schema() == SOURCE, 'source_schema_required_for_first_additive_attempt')
        self.proof(live, previous, public=True)
        require(shutil.disk_usage(self.directory).free >= 12 * GIB, 'insufficient_retained_image_headroom')
        prepare_migration_credentials(self)
        self.verify_migration_identity()
        images = self.candidate_images()
        resources.require_budget(self, source_limits=True)
        resources.ensure_qualification(self)
        resources.prepare(self)
        candidates = self.stage(images)
        self.transition(candidates)
