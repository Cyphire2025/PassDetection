from __future__ import annotations

from fastapi.routing import APIRoute

from app.presentation.api.v1.routes.auth import router


def _dependency_names(path: str) -> set[str]:
    route = next(
        candidate
        for candidate in router.routes
        if isinstance(candidate, APIRoute) and candidate.path == path
    )
    return {
        dependency.call.__name__
        for dependency in route.dependant.dependencies
        if dependency.call is not None
    }


def test_session_cookie_routes_apply_the_expected_csrf_guards() -> None:
    assert "require_trusted_request_origin" in _dependency_names("/login")
    assert "require_cookie_csrf" in _dependency_names("/refresh")
    assert "require_cookie_csrf" in _dependency_names("/logout")
