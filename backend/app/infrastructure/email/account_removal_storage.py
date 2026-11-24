"""Unreferenced object-key observation after email account relational cleanup."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.email_models import EmailArtifactModel
from app.infrastructure.database.models import DistributedDocumentModel


async def _unreferenced_email_storage_keys(
    session: AsyncSession,
    *,
    artifact_storage_keys: tuple[str, ...],
    document_storage_keys: tuple[str, ...],
) -> tuple[str, ...]:
    """Observe remaining references after relational flush; caller owns object deletion."""

    candidate_storage_keys = tuple(dict.fromkeys((*artifact_storage_keys, *document_storage_keys)))
    storage_keys: tuple[str, ...] = ()
    if candidate_storage_keys:
        remaining_artifact_keys = set(
            (
                await session.scalars(
                    select(EmailArtifactModel.storage_key).where(
                        EmailArtifactModel.storage_key.in_(candidate_storage_keys)
                    )
                )
            ).all()
        )
        remaining_document_keys = set(
            (
                await session.scalars(
                    select(DistributedDocumentModel.storage_key).where(
                        DistributedDocumentModel.storage_key.in_(candidate_storage_keys)
                    )
                )
            ).all()
        )
        referenced_keys = remaining_artifact_keys | remaining_document_keys
        storage_keys = tuple(key for key in candidate_storage_keys if key not in referenced_keys)
    return storage_keys
