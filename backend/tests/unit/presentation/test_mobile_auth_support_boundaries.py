from __future__ import annotations

import ast
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.presentation.api.v1.routes import mobile_auth
from app.presentation.api.v1.routes import mobile_auth_otp_support as otp_support
from app.presentation.api.v1.routes import mobile_auth_session_support as session_support

_BACKEND_ROOT = Path(__file__).resolve().parents[3]
_ROUTE_PATH = _BACKEND_ROOT / "app/presentation/api/v1/routes/mobile_auth.py"
_SUPPORT_PATHS = (
    _BACKEND_ROOT / "app/presentation/api/v1/routes/mobile_auth_otp_support.py",
    _BACKEND_ROOT / "app/presentation/api/v1/routes/mobile_auth_session_support.py",
)
def test_mobile_auth_route_order_and_decorators_are_frozen() -> None:
    # Assert the runtime contract directly. Hashing ``ast.dump`` output made
    # this safety check depend on the interpreter's private AST representation
    # and produced different results on Python 3.11 and 3.13.
    assert [
        (route.path, tuple(sorted(route.methods or ())), route.response_model)
        for route in mobile_auth.router.routes
    ] == [
        ("/otp/request", ("POST",), mobile_auth.MobileOTPRequestResponse),
        ("/otp/verify", ("POST",), mobile_auth.MobileOTPVerifyResponse),
        ("/claim/verify", ("POST",), mobile_auth.MobileOTPVerifyResponse),
        ("/login", ("POST",), mobile_auth.MobileTokenResponse),
        ("/activate", ("POST",), mobile_auth.MobileTokenResponse),
        ("/refresh", ("POST",), mobile_auth.MobileTokenResponse),
        ("/me", ("GET",), mobile_auth.MobilePrincipalResponse),
        ("/passenger/trip/switch", ("POST",), mobile_auth.MobileTokenResponse),
        ("/password/change", ("POST",), mobile_auth.MobileTokenResponse),
        ("/logout", ("POST",), None),
        ("/logout-all", ("POST",), None),
    ]


def test_mobile_auth_facade_preserves_direct_helper_imports() -> None:
    otp_names = (
        "_claim_summary",
        "_direct_passenger_otp_rows",
        "_eligible_passenger_identities",
        "_locked_challenge",
        "_matching_passenger_claims",
        "_reconcile_phone_candidate_groups",
        "_validate_passenger_session_identities",
        "_verify_challenge_code",
    )
    session_names = (
        "_normalize_direct_password_client_manager",
        "_principal_display_name",
        "_principal_profile",
        "_refresh_principal",
        "_revoke_session_family",
    )

    for name in otp_names:
        assert getattr(mobile_auth, name) is getattr(otp_support, name)
    for name in session_names:
        assert getattr(mobile_auth, name) is getattr(session_support, name)


def test_issue_session_facade_wires_established_monkeypatch_bindings() -> None:
    tree = ast.parse(_ROUTE_PATH.read_text(encoding="utf-8"))
    issue_session = next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_issue_session"
    )
    dependency_call = next(
        node
        for node in ast.walk(issue_session)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "MobileSessionIssueDependencies"
    )
    bindings = {
        keyword.arg: keyword.value.id
        for keyword in dependency_call.keywords
        if keyword.arg is not None and isinstance(keyword.value, ast.Name)
    }

    assert bindings == {
        "validate_passenger_session_identities": "_validate_passenger_session_identities",
        "revoke_same_device_session": "_revoke_same_device_session",
        "create_refresh_token": "create_mobile_refresh_token",
        "create_access_token": "create_mobile_access_token",
        "create_offline_authorization_lease": "create_mobile_offline_authorization_lease",
        "hash_lookup": "hash_mobile_lookup",
        "hash_refresh_token": "hash_mobile_refresh_token",
        "request_digest": "_request_digest",
    }


def test_auth_support_modules_do_not_import_the_route_facade() -> None:
    for path in _SUPPORT_PATHS:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported_modules = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        }
        assert "app.presentation.api.v1.routes.mobile_auth" not in imported_modules


def test_passenger_session_identity_boundary_rejects_cross_agency_proof() -> None:
    selected = SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        phone_lookup_hash="phone-hash",
        status="eligible",
        revoked_at=None,
    )
    other = SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        phone_lookup_hash=selected.phone_lookup_hash,
        status="eligible",
        revoked_at=None,
    )

    with pytest.raises(HTTPException) as caught:
        otp_support._validate_passenger_session_identities(
            selected_identity=selected,
            authorized_identities=[selected, other],
        )

    assert caught.value.status_code == 403
    assert caught.value.detail == "Passenger verification could not be completed"
