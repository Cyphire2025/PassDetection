"""Replay scoped read parity cases against the actual migrated PostgreSQL schema.

One random local/CI database isolates fixed synthetic fixture identities. Each
case rolls back its own records; no application database is reset or truncated.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import os
import sys
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import URL, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

pytestmark = [pytest.mark.service_integration, pytest.mark.skipif(
    os.getenv("RUN_SERVICE_INTEGRATION") != "1", reason="isolated PostgreSQL required")]

CASES = [
    ("group_reads", "groups_fixture", name) for name in (
        "empty_import_only_and_duplicate_names_are_explicit",
        "passport_operational_and_broadcast_entries_are_not_collapsed",
        "keyset_ties_large_pagination_and_newer_insert",
        "cursor_tampering_filter_binding_and_expiry",
        "names_are_literal_and_deleted_history_is_explicit",
        "role_and_deactivation_are_rechecked",
        "between_page_rename_is_live_and_cursor_is_actor_bound",
    )
] + [
    ("operations_reads", "office_reads", name) for name in (
        "empty_import_only_group_and_invalid_scopes",
        "tour_retains_inactive_assignment_and_original_scan_without_credentials",
        "rooming_selection_allocation_checkin_and_live_membership_are_distinct",
        "menu_platform_is_not_agency_and_saved_entry_names_survive_library_changes",
        "directory_minimal_fields_distinct_counts_and_contact_audit",
        "bounded_keysets_namespace_binding_and_creation_cutoff",
        "deleted_group_opt_in_live_actor_and_invalid_selectors",
        "inconsistent_cross_agency_links_do_not_enter_group_projections",
    )
] + [
    ("content_reads", "content_reads", name) for name in (
        "unconfigured_gc_and_empty_owned_mailboxes_are_explicit",
        "gc_versions_optional_content_and_shared_availability",
        "personal_mailbox_boundary_and_credential_omission_for_superadmin",
        "content_pages_cursor_binding_role_and_bounds",
    )
] + [
    ("document_reads", "document_reads", name) for name in (
        "empty_import_only_group_missing_agency_and_retained_opt_in",
        "document_privacy_provenance_and_operational_roster_are_separate",
        "batches_and_jobs_keep_incomplete_and_old_revision_evidence",
        "document_keysets_and_filter_contact_and_tenant_binding",
        "document_bounds_types_and_live_role",
    )
]

CASES += [("dashboard_detail_reads", "detail_fixture", name) for name in (
    "full_passport_fields_and_canonical_expiry_without_business_changes",
    "roster_hydrates_real_identity_only_cache_and_retains_revision_fence",
    "whatsapp_dashboard_unidentified_and_imported_fields_are_canonical",
    "staff_code_search_matches_saved_editor_precedence_and_explicit_clear",
    "all_stored_whatsapp_imports_removed_contacts_and_provenance_are_paged",
    "qr_and_welcome_observation_never_issues_tokens_or_recovers_delivery",
    "document_review_and_delivery_eligibility_are_pure_without_storage",
    "image_library_and_ai_job_reads_do_not_ensure_original_or_dispatch",
    "all_delivery_kinds_preserve_saved_statuses_content_and_tenant_scope",
    "complete_delivery_history_passes_one_hundred_rows_and_filters",
    "common_document_native_pages_reach_beyond_previous_two_hundred_cap",
    "owner_email_review_pages_reach_beyond_previous_two_hundred_fifty_cap",
    "qr_root_cursor_ignores_query_clock_and_reaches_every_field",
)]


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def postgres_reads():
    host, source = os.environ.get("POSTGRES_HOST", "localhost"), os.environ["POSTGRES_DB"]
    if host not in {"localhost", "127.0.0.1", "postgres", "db"} or (
        source != "test_db" and not source.startswith("passdetection_ci_")):
        pytest.fail("Read parity requires an isolated local/CI PostgreSQL cluster")
    name = "passdetection_ci_mcp_reads_" + uuid.uuid4().hex[:12]
    url = URL.create("postgresql+asyncpg", username=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"], host=host,
        port=int(os.environ.get("POSTGRES_PORT", "5432")), database=source)
    admin = create_async_engine(url, poolclass=NullPool, isolation_level="AUTOCOMMIT")
    engine = create_async_engine(url.set(database=name), poolclass=NullPool)
    async with admin.connect() as connection:
        await connection.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        process = await asyncio.create_subprocess_exec(sys.executable, "-m", "alembic", "upgrade", "head",
            cwd=Path(__file__).resolve().parents[2], env={**os.environ, "POSTGRES_DB": name},
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        output, _ = await asyncio.wait_for(process.communicate(), 90)
        assert process.returncode == 0, output.decode("utf-8", errors="replace")[-4000:]
        yield engine
    finally:
        await engine.dispose()
        async with admin.connect() as connection:
            await connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        await admin.dispose()


@pytest.mark.parametrize("module_name,fixture_name,case_name", CASES, ids=[case[2] for case in CASES])
async def test_postgresql_read_parity(postgres_reads, module_name, fixture_name, case_name, test_settings, monkeypatch):
    module = importlib.import_module(f"tests.integration.test_mcp_{module_name}")
    async with postgres_reads.connect() as connection:
        transaction = await connection.begin()
        async with AsyncSession(connection, expire_on_commit=False, join_transaction_mode="create_savepoint") as session:
            try:
                factory = getattr(module, fixture_name).__wrapped__
                fixture = await factory(session, **({"test_settings": test_settings} if "test_settings" in inspect.signature(factory).parameters else {}))
                test = getattr(module, f"test_{case_name}")
                await test(fixture, **({"monkeypatch": monkeypatch} if "monkeypatch" in inspect.signature(test).parameters else {}))
            finally:
                await transaction.rollback()
