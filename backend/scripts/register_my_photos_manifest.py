#!/usr/bin/env python3
"""Register an already-direct-uploaded My Photos manifest for indexing.

The command is intentionally interactive for workforce authentication and
TOTP step-up.  It accepts metadata from a bounded JSON file, never image bytes.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import sys
import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.domain.entities.entities import User
    from app.infrastructure.my_photos.gallery_ingestion import GalleryManifestRequest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

_MAX_MANIFEST_FILE_BYTES = 1_048_576
_MAX_MANIFEST_SET_BYTES = 50 * _MAX_MANIFEST_FILE_BYTES
_MAX_MANIFEST_FILES = 50


def _arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Verify and register a bounded My Photos S3 manifest; no media bytes "
            "are uploaded by this command."
        )
    )
    commands = parser.add_subparsers(dest="command", required=True)
    register = commands.add_parser(
        "register",
        help="Register one or more batch JSON files using one password and TOTP step-up",
    )
    register.add_argument(
        "manifests",
        type=Path,
        nargs="+",
        help="Ordered batch JSON files, or directories containing batch JSON files",
    )
    register.add_argument(
        "--finalize",
        action="store_true",
        help="Finalize only after the complete declared batch set registers successfully",
    )
    for command_name in ("status", "cancel"):
        command = commands.add_parser(command_name)
        command.add_argument("--agency-id", required=True, type=uuid.UUID)
        command.add_argument("--group-id", required=True, type=uuid.UUID)
        command.add_argument("--manifest-identity", required=True)
    for command in (register, commands.choices["status"], commands.choices["cancel"]):
        command.add_argument("--actor-email", required=True, help="Active agency/super-admin email")
    return parser.parse_args(argv)


def _load_manifest(path: Path) -> GalleryManifestRequest:
    from app.infrastructure.my_photos.gallery_ingestion import GalleryManifestRequest

    resolved = path.resolve(strict=True)
    if not resolved.is_file() or resolved.suffix.lower() != ".json":
        raise ValueError("Manifest must be a JSON file")
    size = resolved.stat().st_size
    if not 1 <= size <= _MAX_MANIFEST_FILE_BYTES:
        raise ValueError("Manifest file is outside the 1 MiB control-plane limit")
    return GalleryManifestRequest.model_validate_json(resolved.read_text(encoding="utf-8"))


def _manifest_paths(inputs: Sequence[Path]) -> tuple[Path, ...]:
    paths: list[Path] = []
    for item in inputs:
        resolved = item.resolve(strict=True)
        if resolved.is_dir():
            paths.extend(sorted(resolved.glob("*.json"), key=lambda path: path.name))
        elif resolved.is_file():
            paths.append(resolved)
        else:
            raise ValueError("Manifest input must be a JSON file or directory")
    unique = tuple(dict.fromkeys(path.resolve() for path in paths))
    if not 1 <= len(unique) <= _MAX_MANIFEST_FILES:
        raise ValueError("Manifest input must contain between 1 and 50 JSON batches")
    if any(path.suffix.lower() != ".json" for path in unique):
        raise ValueError("Every manifest batch must be a JSON file")
    total_size = sum(path.stat().st_size for path in unique)
    if not 1 <= total_size <= _MAX_MANIFEST_SET_BYTES:
        raise ValueError("Manifest batch metadata exceeds the bounded 50 MiB set")
    return unique


def _ordered_manifest_requests(
    inputs: Sequence[Path], *, finalize: bool
) -> tuple[GalleryManifestRequest, ...]:
    requests = tuple(_load_manifest(path) for path in _manifest_paths(inputs))
    first = requests[0]
    header = first.model_dump(mode="json", exclude={"assets", "batch_index", "finalize"})
    if any(
        request.model_dump(mode="json", exclude={"assets", "batch_index", "finalize"}) != header
        for request in requests[1:]
    ):
        raise ValueError("Every batch file must declare the same manifest header")
    by_index = {request.batch_index: request for request in requests}
    if len(by_index) != len(requests):
        raise ValueError("Manifest batch indexes must be unique")
    ordered = tuple(by_index[index] for index in sorted(by_index))
    if finalize and tuple(sorted(by_index)) != tuple(range(first.batch_count)):
        raise ValueError("--finalize requires every declared batch index")
    return tuple(
        request.model_copy(update={"finalize": bool(finalize and position == len(ordered) - 1)})
        for position, request in enumerate(ordered)
    )


async def _register_requests(
    service: Any,
    *,
    actor: Any,
    mfa_verified_at: datetime,
    requests: Sequence[Any],
    dispatch: Callable[[uuid.UUID], None],
    progress: Callable[[dict[str, object]], None] | None = None,
) -> tuple[Any, ...]:
    results: list[Any] = []
    for request in requests:
        result = await service.register_batch(
            actor=actor,
            mfa_verified_at=mfa_verified_at,
            request=request,
            dispatch=dispatch,
        )
        results.append(result)
        if progress is not None:
            progress(
                {
                    "batch_index": request.batch_index,
                    "received_asset_count": result.received_asset_count,
                    "total_asset_count": result.total_asset_count,
                    "state": result.state,
                    "checkpoint": result.content_fingerprint,
                }
            )
    return tuple(results)


async def _authenticate_operator(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    totp_code: str,
    now: datetime,
) -> User:
    from app.core.security.identity_security import (
        IdentitySecurityError,
        decrypt_mfa_secret,
        reencrypt_mfa_secret_if_needed,
        verify_totp,
    )
    from app.core.security.password import verify_password
    from app.domain.entities.entities import UserRole
    from app.domain.exceptions.exceptions import AuthenticationError
    from app.infrastructure.repositories.identity_security_repository import (
        IdentitySecurityRepository,
    )
    from app.infrastructure.repositories.user_repository import UserRepository

    normalized_email = email.strip().lower()
    async with session.begin():
        user = await UserRepository(session).get_by_email(normalized_email)
        if (
            user is None
            or not user.is_active
            or user.credential_state != "active"
            or user.role not in {UserRole.SUPER_ADMIN, UserRole.AGENCY_ADMIN}
            or not verify_password(password, user.hashed_password)
        ):
            raise AuthenticationError("Operator authentication failed")
        repository = IdentitySecurityRepository(session)
        state = await repository.get_state(user.id, lock=True)
        if (
            state is None
            or state.credential_state != "active"
            or state.mfa_enabled_at is None
            or state.mfa_secret_ciphertext is None
        ):
            raise AuthenticationError("Operator MFA is not enabled")
        try:
            secret = decrypt_mfa_secret(state.mfa_secret_ciphertext)
        except IdentitySecurityError as exc:
            raise AuthenticationError("Operator authentication failed") from exc
        counter = verify_totp(
            secret,
            totp_code.strip(),
            now=now,
            last_accepted_counter=state.mfa_last_counter,
        )
        if counter is None:
            raise AuthenticationError("Operator authentication failed")
        state.mfa_last_counter = counter
        state.mfa_secret_ciphertext = reencrypt_mfa_secret_if_needed(state.mfa_secret_ciphertext)
        state.updated_at = now
    return user


async def _run(args: argparse.Namespace) -> dict[str, object]:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.config.settings import get_settings
    from app.infrastructure.my_photos.dispatcher import enqueue_index_job
    from app.infrastructure.my_photos.gallery_ingestion import (
        GalleryManifestLocator,
        GalleryManifestRegistrationService,
    )
    from app.infrastructure.my_photos.providers import build_provider_bundle

    requests = (
        _ordered_manifest_requests(args.manifests, finalize=args.finalize)
        if args.command == "register"
        else ()
    )
    password = getpass.getpass("Password: ")
    totp_code = getpass.getpass("Authenticator code: ")
    now = datetime.now(tz=UTC)
    settings = get_settings()
    providers = build_provider_bundle(settings)
    engine = create_async_engine(settings.database.async_url, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            actor = await _authenticate_operator(
                session,
                email=args.actor_email,
                password=password,
                totp_code=totp_code,
                now=now,
            )
            service = GalleryManifestRegistrationService(
                session,
                settings=settings,
                providers=providers,
            )
            if args.command == "register":
                results = await _register_requests(
                    service,
                    actor=actor,
                    mfa_verified_at=now,
                    requests=requests,
                    dispatch=enqueue_index_job,
                    progress=lambda checkpoint: print(
                        json.dumps({"progress": checkpoint}, sort_keys=True),
                        file=sys.stderr,
                    ),
                )
                result = results[-1]
            else:
                locator = GalleryManifestLocator(
                    agency_id=args.agency_id,
                    group_id=args.group_id,
                    manifest_identity=args.manifest_identity,
                )
                if args.command == "status":
                    status_result = await service.manifest_status(
                        actor=actor,
                        mfa_verified_at=now,
                        locator=locator,
                    )
                else:
                    status_result = await service.cancel_manifest(
                        actor=actor,
                        mfa_verified_at=now,
                        locator=locator,
                    )
    finally:
        await engine.dispose()
    if args.command != "register":
        return {
            "manifest_id": str(status_result.manifest_id),
            "gallery_id": str(status_result.gallery_id),
            "index_job_id": (
                str(status_result.index_job_id) if status_result.index_job_id is not None else None
            ),
            "target_revision": status_result.target_revision,
            "received_asset_count": status_result.received_asset_count,
            "total_asset_count": status_result.total_asset_count,
            "batch_count": status_result.batch_count,
            "received_batch_indices": list(status_result.received_batch_indices),
            "missing_batch_indices": list(status_result.missing_batch_indices),
            "state": status_result.state,
            "cancellation_requested": status_result.cancellation_requested,
            "content_fingerprint": status_result.content_fingerprint,
            "updated_at": status_result.updated_at.isoformat(),
        }
    return {
        "manifest_id": str(result.manifest_id),
        "gallery_id": str(result.gallery_id),
        "index_job_id": str(result.index_job_id) if result.index_job_id is not None else None,
        "target_revision": result.target_revision,
        "received_asset_count": result.received_asset_count,
        "total_asset_count": result.total_asset_count,
        "batch_count": result.batch_count,
        "state": result.state,
        "batch_replay": result.batch_replay,
        "manifest_replay": result.manifest_replay,
        "content_fingerprint": result.content_fingerprint,
        "dispatch_state": result.dispatch_state,
        "processed_batch_count": len(results),
    }


def main(argv: list[str] | None = None) -> None:
    try:
        result = asyncio.run(_run(_arguments(argv)))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"[my-photos] Manifest rejected: {exc}") from exc
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
