from __future__ import annotations

import io

from fastapi import UploadFile
from fastapi.routing import APIRoute

from app.presentation.api.v1.routes import passports


def test_document_import_upload_sources_measure_spools_without_materializing_bodies() -> None:
    upload = UploadFile(
        file=io.BytesIO(b"bounded-upload"),
        filename="STF_A1_FRONT.jpg",
    )

    sources = passports._passport_document_upload_sources([upload])  # noqa: SLF001

    assert len(sources) == 1
    assert sources[0].size_bytes == len(b"bounded-upload")
    assert sources[0].stream.tell() == 0
    assert sources[0].stream.read() == b"bounded-upload"


def test_document_import_preview_and_save_require_cookie_csrf() -> None:
    expected_paths = {
        "/groups/{group_id}/import-passports/preview",
        "/groups/{group_id}/import-passports/save",
    }
    routes = {
        route.path: route
        for route in passports.router.routes
        if isinstance(route, APIRoute) and route.path in expected_paths
    }

    assert set(routes) == expected_paths
    for route in routes.values():
        dependency_names = {
            dependency.call.__name__
            for dependency in route.dependant.dependencies
            if dependency.call is not None
        }
        assert "require_cookie_csrf" in dependency_names
