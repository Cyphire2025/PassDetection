"""Retained business rows and new display/update fields on migrated PostgreSQL."""

import os

import pytest

from scripts.qualify_document_distribution_upgrade import qualify

pytestmark = [pytest.mark.service_integration, pytest.mark.skipif(
    os.getenv("RUN_SERVICE_INTEGRATION") != "1", reason="isolated PostgreSQL required",
)]


def test_document_distribution_upgrade_and_downgrade_retain_existing_data():
    result = qualify(release_helper=True)
    assert result["preexisting_rows_and_fields_retained"] is True
    assert result["release_helper"]["source_and_intermediate_resume_passed"] is True
    assert result["release_helper"]["changed_rows_catalog_and_early_new_values_rejected"] is True
    assert result["messages_sent"] == 0
