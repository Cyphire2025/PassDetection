"""Retained Fast rollout for the exact 0140 to 0141 branding additions.

All historical resources survive. A fenced backup and original row/catalog/ACL
baseline precede DDL. Once 0141 commits, recovery only starts validated 0141
candidates; it never restarts a source-schema writer or downgrades data.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from mcp_direct_build import command
from mcp_direct_release import bound_original
from mcp_direct_state import APPLICATION, INFRASTRUCTURE, WORKERS
from release_code_update import environment
from release_companies_credentials import prepare_migration_credentials, preflight_migration_credentials
from release_companies_runtime import bound_migration_helper, run_migration_helper
from release_mcp_database import digest_json
from release_reliability import file_sha256
from release_retained_update import ACTIVE, RetainedUpdate, require
from release_workspace_branding_contract import SOURCE, TARGET, source_contract
from release_workspace_branding_policy import validate_source


class WorkspaceBrandingUpdate(RetainedUpdate):
    candidate_schema = TARGET
    installed = False

    def initial_schema(self) -> str:
        return TARGET if getattr(self, 'installed', False) else SOURCE

    def retention_schema(self) -> str:
        return self.record.get('schema', self.initial_schema())

    def compatibility(self, previous: str) -> None:
        if getattr(self, 'installed', False):
            return super().compatibility(previous)
        validate_source(self.source, previous, self.revision)

    def prepare_images(self) -> None:
        if not self.installed:
            prepare_migration_credentials(self)
            preflight_migration_credentials(self)

    def fast_images(self) -> dict:
        if self.installed:
            return super().fast_images()
        with self.background_quiescence():
            images = self.build_fast_images()
            self.event('branding-images-built', image_ids=images)
            receipt = self.directory / 'branding-migration-rehearsal.json'
            command(sys.executable, '-B', str(self.source / 'scripts/qa/qualify_branding_migration.py'),
                    '--image', images['backend'], '--revision', self.revision,
                    '--postgres-image', self.record['live']['db']['Image'], '--output', str(receipt), timeout=1800)
            self.event('branding-migration-rehearsed', branding_rehearsal=json.loads(receipt.read_text()),
                       branding_rehearsal_sha256=hashlib.sha256(receipt.read_bytes()).hexdigest())
        return images

    def backup(self) -> None:
        if self.installed:
            super().backup()
        # The additive lane captures its original backup with all writers fenced.

    def verify_fence(self) -> None:
        live = self.record['live']
        for name in ACTIVE:
            require(not bound_original(live[name])['State']['Running'], 'original_writer_running')
            require(not bound_original(self.record['candidates'][name])['State']['Running'], 'candidate_writer_running')
        for helper in self.record.get('migration_helpers', []):
            require(not bound_migration_helper(helper)['State']['Running'], 'migration_helper_still_running')
        require({row['Id'] for row in self.rows()} == {live[name]['Id'] for name in INFRASTRUCTURE}, 'writers_not_fenced')
        self.retention()

    def verify_evidence(self) -> None:
        from qa.qualify_branding_migration import CHECKS
        receipt = self.directory / 'branding-migration-rehearsal.json'
        require(hashlib.sha256(receipt.read_bytes()).hexdigest() == self.record['branding_rehearsal_sha256'],
                'branding_rehearsal_changed')
        proof = json.loads(receipt.read_text())
        require(proof == self.record['branding_rehearsal'] and proof.get('status') == 'passed'
                and proof.get('source_revision') == self.revision
                and proof.get('backend_image_id') == self.record['image_ids']['backend']
                and proof.get('source_contract_sha256') == digest_json(source_contract(self.source))
                and proof.get('source_schema') == SOURCE and proof.get('target_schema') == TARGET
                and proof.get('full_ci_qualified') is False and proof.get('owned_resources_removed') is True
                and proof.get('checks') == CHECKS, 'bound_branding_rehearsal_required')

    def before_candidate_start(self) -> None:
        if self.installed:
            return super().before_candidate_start()
        self.verify_evidence()
        self.verify_fence()
        if 'backup' not in self.record:
            require(self.schema() == SOURCE, 'original_backup_required')
            super().backup()
            path = Path(self.record['backup'])
            self.event('branding-fenced-backup', backup_sha256=file_sha256(path))
        path = Path(self.record['backup'])
        require(path == self.directory / 'pre-release.dump'
                and file_sha256(path) == self.record['backup_sha256'], 'original_backup_changed')
        proof = digest_json({'revision': self.revision, 'image_ids': self.record['image_ids'],
                             'contract': source_contract(self.source), 'backup_sha256': self.record['backup_sha256']})
        request = {'image_id': self.record['image_ids']['backend'], 'proof': {'sha256': proof}, 'timeout': 1800,
                   'environment': {'MCP_RELEASE_PROOF_SHA256': proof},
                   'arguments': ('python', 'scripts/release_workspace_branding_upgrade.py', '--contract-json',
                                 json.dumps(source_contract(self.source), sort_keys=True))}
        if self.record.get('database_validation') == proof:
            require(self.schema() == TARGET, 'validated_branding_schema_changed')
            return
        baseline = self.record.get('branding_baseline')
        if baseline is None:
            require(self.schema() == SOURCE, 'original_branding_baseline_required')
            baseline = run_migration_helper(self, {**request, 'arguments': (*request['arguments'], '--capture-baseline')})
            self.event('branding-baseline-captured', branding_baseline=baseline)
        require(baseline.get('status') == 'baseline_captured' and baseline.get('release_proof_sha256') == proof
                and baseline.get('source_schema') == SOURCE and baseline.get('target_schema') == TARGET,
                'branding_baseline_binding_changed')
        request['environment']['MCP_RELEASE_BASELINE_SHA256'] = baseline['preservation_sha256']
        # A helper can commit before the host receives its result. Permit only
        # SOURCE/TARGET in retention while it runs, and retain that state durably.
        self.event('branding-migration-starting', migration_in_progress=True)
        result = run_migration_helper(self, request)
        require(result.get('status') in {'upgraded', 'already_at_target'}
                and result.get('release_proof_sha256') == proof
                and result.get('preservation_sha256') == baseline['preservation_sha256']
                and result.get('source_schema') == SOURCE and result.get('target_schema') == TARGET
                and result.get('new_columns_null') is True and result.get('runtime_grants_verified') is True
                and result.get('automatic_downgrade') is False and self.schema() == TARGET,
                'complete_branding_migration_validation_required')
        self.event('branding-migration-verified', schema=TARGET, migration_in_progress=False, database_validation=proof)

    def retention(self) -> None:
        if self.record.get('migration_in_progress'):
            require(self.schema() in {SOURCE, TARGET}, 'unexpected_branding_schema')
            self.record['schema'] = self.schema()
        super().retention()

    def recover(self) -> None:
        if getattr(self, 'installed', False) or 'branding_rehearsal' not in self.record:
            return super().recover()
        # A timed-out helper may still be applying DDL. Observe it first.
        for helper in self.record.get('migration_helpers', []):
            require(not bound_migration_helper(helper)['State']['Running'], 'migration_helper_still_running')
        if self.schema() == SOURCE:
            self.record.update(schema=SOURCE, migration_in_progress=False)
            return super().recover()
        require(self.schema() == TARGET, 'unexpected_branding_schema')
        self.event('branding-forward-recovery', schema=TARGET, migration_in_progress=True)
        for name in ('nginx', 'email-beat', 'backend', 'frontend', *WORKERS):
            self.fence_candidate(self.record['candidates'][name])
            self.stop(bound_original(self.record['live'][name]))
        self.before_candidate_start()
        candidates = self.record['candidates']
        for name in ('backend', 'frontend', *WORKERS, 'email-beat'):
            if name not in self.paused_services():
                self.start(candidates[name])
        self.proof({name: candidates[name] for name in APPLICATION}, self.revision, public=False)
        self.start(candidates['nginx'])
        self.proof(candidates, self.revision, public=True)
        require({row['Id'] for row in self.rows()} == {row['Id'] for name, row in candidates.items()
                if name not in self.paused_services()} | {self.record['live'][name]['Id'] for name in INFRASTRUCTURE},
                'unexpected_running_container')
        self.event('complete', all_prior_resources_retained=True, automatic_downgrade=False)

    def run(self) -> None:
        backend = [row for row in self.rows() if row['Config']['Labels'].get('com.docker.compose.service') == 'backend']
        require(len(backend) == 1, 'ambiguous_running_backend')
        current = environment(backend[0]).get('EXPECTED_DATABASE_SCHEMA_REVISION')
        require(current in {SOURCE, TARGET}, 'unsupported_live_branding_schema')
        self.installed = current == TARGET
        from release_pdf_checking_profile import LABEL, PROFILE
        if backend[0]['Config']['Labels'].get(LABEL) == PROFILE:
            self.pause_email_and_photos = True
        # This additive transition currently has exact-image Fast rehearsal only.
        require(self.installed or self.mode == 'fast', 'branding_additive_requires_operator_fast')
        if not self.installed:
            # Retain the installed feature-pause profile, including its scheduler.
            require(backend[0]['Config']['Labels'].get(LABEL) == PROFILE, 'installed_paused_profile_required')
        super().run()
