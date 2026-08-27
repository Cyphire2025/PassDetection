"""Explicit trusted-development bootstrap for the synthetic My Photos gallery."""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid

from sqlalchemy import and_, select

from app.application.security.mobile_access_policy import AuthorizedMobileTrip
from app.core.config.settings import get_settings
from app.infrastructure.database.gc_mobile_models import GCGroupAccessModel
from app.infrastructure.database.models import ClientGroupModel
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.my_photos.development_fixture import (
    bootstrap_development_gallery,
)


async def _bootstrap(
    *,
    group_id: uuid.UUID,
    access_id: uuid.UUID,
    maximum_batches: int | None,
) -> dict[str, int | str]:
    settings = get_settings()
    config = settings.my_photos
    if (
        settings.app_env != "development"
        or not config.development_fixtures_enabled
        or {
            config.liveness_provider,
            config.face_search_provider,
            config.media_provider,
        }
        != {"development"}
    ):
        raise RuntimeError(
            "My Photos demo bootstrap requires APP_ENV=development, explicit fixture "
            "enablement, and all three development providers"
        )

    async with AsyncSessionFactory() as session:
        row = (
            await session.execute(
                select(GCGroupAccessModel, ClientGroupModel)
                .join(
                    ClientGroupModel,
                    and_(
                        ClientGroupModel.id == GCGroupAccessModel.group_id,
                        ClientGroupModel.agency_id == GCGroupAccessModel.agency_id,
                    ),
                )
                .where(
                    GCGroupAccessModel.id == access_id,
                    GCGroupAccessModel.group_id == group_id,
                    ClientGroupModel.id == group_id,
                    ClientGroupModel.deleted_at.is_(None),
                )
            )
        ).one_or_none()
        if row is None:
            raise RuntimeError("The supplied development group/access locator was not found")
        access, group = row
        gallery = await bootstrap_development_gallery(
            session,
            trip=AuthorizedMobileTrip(
                group=group,
                access=access,
                principal_type="passenger",
                passenger_identity=None,
            ),
            settings=settings,
            maximum_batches=maximum_batches,
        )
        return {
            "status": gallery.status,
            "published_revision": gallery.published_revision,
            "total_asset_count": gallery.total_asset_count,
            "indexed_asset_count": gallery.indexed_asset_count,
            "failed_asset_count": gallery.failed_asset_count,
        }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Seed the deterministic 5,000-asset My Photos gallery in explicit local "
            "development only. This command never uses AWS or real passenger media."
        )
    )
    parser.add_argument("--group-id", type=uuid.UUID, required=True)
    parser.add_argument("--access-id", type=uuid.UUID, required=True)
    parser.add_argument(
        "--maximum-batches",
        type=int,
        default=None,
        help="Optional positive batch cap for testing interruption and resume.",
    )
    return parser


def main() -> None:
    parser = _parser()
    args = parser.parse_args()
    if args.maximum_batches is not None and args.maximum_batches < 1:
        parser.error("--maximum-batches must be positive")
    try:
        result = asyncio.run(
            _bootstrap(
                group_id=args.group_id,
                access_id=args.access_id,
                maximum_batches=args.maximum_batches,
            )
        )
    except RuntimeError as exc:
        parser.error(str(exc))
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
