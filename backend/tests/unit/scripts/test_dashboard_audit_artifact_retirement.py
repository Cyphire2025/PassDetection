"""Closed retirement manifests preserve traceability without reading media."""

from __future__ import annotations

import copy
import json

import pytest

from tests.unit.scripts.test_dashboard_audit_review_resolutions import inventory

PREFIX = "assets/branding/global-connect/journey-film/qa/browser-color-probes/"
FILENAMES = (
    "full-srgb.mp4",
    "index.html",
    "limited-709.mp4",
    "limited-srgb.mp4",
    "limited-unspecified.mp4",
)


def manifest():
    return {
        "schema_version": 1,
        "status": "retired",
        "source_cohort": PREFIX.rstrip("/"),
        "closed_entry_count": 5,
        "binary_payloads_embedded": False,
        "files": [
            {
                "path": PREFIX + name,
                "original_path": PREFIX + name,
                "archive_path": "Not related to project/retired-branding-experiments/"
                + PREFIX
                + name,
                "sha256": "a" * 64,
                "archive_sha256": "a" * 64,
                "bytes": 1,
                "status": "retired",
                "asset_metadata_only": True,
            }
            for name in FILENAMES
        ],
    }


def write(report, document, name="journey-color-probes-retirement-manifest.json"):
    (report / name).write_text(json.dumps(document), encoding="utf-8")


def test_closed_probes_survive_fresh_history_without_opening_ignored_media(tmp_path, monkeypatch):
    document = manifest()
    write(tmp_path, document)
    monkeypatch.setattr(inventory, "REPORT", tmp_path)
    # The archive can be absent in a clean checkout: metadata is the evidence.
    result = inventory.retired_source_history()
    assert set(result) == {PREFIX + name for name in FILENAMES}
    assert all(row["review_scope"] == "retired" and row["lines"] == 0 for row in result.values())


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "duplicate",
        "foreign",
        "wrong_archive",
        "wrong_hash",
        "boolean_bytes",
        "payload",
        "metadata_false",
        "schema_bool",
        "wrong_cohort",
    ],
)
def test_probe_metadata_cannot_retire_another_asset_or_invent_source(
    tmp_path, monkeypatch, mutation
):
    document = manifest()
    row = document["files"][0]
    if mutation == "missing":
        document["files"].pop()
    elif mutation == "duplicate":
        document["files"][1] = copy.deepcopy(row)
    elif mutation == "foreign":
        row["path"] = row["original_path"] = "frontend/public/current-logo.svg"
        row["archive_path"] = "Not related to project/retired-branding-experiments/" + row["path"]
    elif mutation == "wrong_archive":
        row["archive_path"] = "../outside.mp4"
    elif mutation == "wrong_hash":
        row["archive_sha256"] = "b" * 64
    elif mutation == "boolean_bytes":
        row["bytes"] = True
    elif mutation == "payload":
        row["source"] = "embedded bytes are not source-review evidence"
    elif mutation == "metadata_false":
        row["asset_metadata_only"] = False
    elif mutation == "schema_bool":
        document["schema_version"] = True
    else:
        document["source_cohort"] = "assets/current"
    write(tmp_path, document)
    monkeypatch.setattr(inventory, "REPORT", tmp_path)
    with pytest.raises(ValueError):
        inventory.retired_source_history()


def test_placeholder_is_one_exact_path_with_bound_archive_identity(tmp_path, monkeypatch):
    row = {
        "path": "backend/placeholder.txt",
        "original_path": "backend/placeholder.txt",
        "archive_path": "Not related to project/retired-unused-placeholder/backend/placeholder.txt",
        "sha256": "c" * 64,
        "archive_sha256": "c" * 64,
        "bytes": 77,
        "status": "retired",
        "asset_metadata_only": True,
        "physical_lines": 1,
    }
    document = {
        "schema_version": 1,
        "closed_entry_count": 1,
        "binary_payloads_embedded": False,
        "files": [row],
    }
    write(tmp_path, document, "unused-placeholder-retirement-manifest.json")
    monkeypatch.setattr(inventory, "REPORT", tmp_path)
    assert inventory.retired_source_history()["backend/placeholder.txt"]["lines"] == 1
    row["path"] = row["original_path"] = "backend/app/main.py"
    row["archive_path"] = "Not related to project/retired-unused-placeholder/" + row["path"]
    write(tmp_path, document, "unused-placeholder-retirement-manifest.json")
    with pytest.raises(ValueError):
        inventory.retired_source_history()
