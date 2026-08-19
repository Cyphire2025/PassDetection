from __future__ import annotations

import ast
import hashlib
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
_ROUTE_CONTRACT_SHA256 = "ea22e5f33f7566b1514cd8dd485413493dcbfa07be27f5216dd361925a8165d8"


def _route_contract_digest() -> str:
    tree = ast.parse(_ROUTE_PATH.read_text(encoding="utf-8"))
    contract: list[tuple[object, ...]] = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        decorators = [
            ast.dump(decorator, include_attributes=False)
            for decorator in node.decorator_list
            if isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Attribute)
            and isinstance(decorator.func.value, ast.Name)
            and decorator.func.value.id == "router"
        ]
        if not decorators:
            continue
        contract.append(
            (
                node.name,
                decorators,
                ast.dump(node.args, include_attributes=False),
                ast.dump(node.returns, include_attributes=False) if node.returns else None,
            )
        )
    return hashlib.sha256(repr(contract).encode()).hexdigest()


def test_mobile_auth_route_order_and_decorators_are_frozen() -> None:
    assert [route.path for route in mobile_auth.router.routes] == [
        "/otp/request",
        "/otp/verify",
        "/claim/verify",
        "/login",
        "/activate",
        "/refresh",
        "/me",
        "/passenger/trip/switch",
        "/password/change",
        "/logout",
        "/logout-all",
    ]
    assert _route_contract_digest() == _ROUTE_CONTRACT_SHA256


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
