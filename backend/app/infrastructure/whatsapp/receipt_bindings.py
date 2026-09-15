"""Write-once correlation between a provider message and its original attempt."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TypeAlias, cast

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.gc_mobile_models import MobileOTPChallengeModel
from app.infrastructure.database.models import (
    DocumentWhatsAppDeliveryModel,
    PassengerQrWhatsAppDeliveryModel,
    WhatsAppMessageLogModel,
    WhatsAppPhoneWelcomeAttemptModel,
    WhatsAppProviderMessageBindingModel,
)

ReceiptSource: TypeAlias = (
    WhatsAppMessageLogModel
    | WhatsAppPhoneWelcomeAttemptModel
    | DocumentWhatsAppDeliveryModel
    | PassengerQrWhatsAppDeliveryModel
    | MobileOTPChallengeModel
)
ReceiptSourceModel: TypeAlias = (
    type[WhatsAppMessageLogModel]
    | type[WhatsAppPhoneWelcomeAttemptModel]
    | type[DocumentWhatsAppDeliveryModel]
    | type[PassengerQrWhatsAppDeliveryModel]
    | type[MobileOTPChallengeModel]
)
SOURCE_MODELS: dict[str, ReceiptSourceModel] = {
    "broadcast": WhatsAppMessageLogModel,
    "traveller_welcome": WhatsAppPhoneWelcomeAttemptModel,
    "document": DocumentWhatsAppDeliveryModel,
    "qr": PassengerQrWhatsAppDeliveryModel,
    "otp": MobileOTPChallengeModel,
}


class ProviderBindingConflict(RuntimeError):
    """A provider identifier must never be reassigned to another attempt."""


def source_identity(source: ReceiptSource) -> tuple[str, uuid.UUID, uuid.UUID]:
    for kind, model in SOURCE_MODELS.items():
        if isinstance(source, model):
            attempt = (
                source.send_batch_id
                if isinstance(
                    source, (DocumentWhatsAppDeliveryModel, PassengerQrWhatsAppDeliveryModel)
                )
                else source.id
            )
            return kind, source.id, attempt
    raise TypeError("Unsupported WhatsApp receipt source")


def source_provider_id(source: ReceiptSource) -> str | None:
    return (
        source.provider_reference
        if isinstance(source, MobileOTPChallengeModel)
        else source.provider_message_id
    )


async def bind_provider_message(
    session: AsyncSession,
    *,
    source_kind: str,
    source_id: uuid.UUID,
    source_attempt_key: uuid.UUID,
    provider_phone_number_id: str | None,
    provider_message_id: str,
    agency_id: uuid.UUID | None,
) -> WhatsAppProviderMessageBindingModel:
    """Insert or confirm an identical binding; the caller owns the transaction."""
    account = provider_phone_number_id or ""
    if (
        source_kind not in SOURCE_MODELS
        or not 0 < len(provider_message_id) <= 255
        or len(account) > 255
    ):
        raise ValueError("Invalid WhatsApp provider binding")
    insert = sqlite_insert if session.get_bind().dialect.name == "sqlite" else pg_insert
    await session.execute(
        insert(WhatsAppProviderMessageBindingModel)
        .values(
            id=uuid.uuid4(),
            provider_phone_number_id=account,
            provider_message_id=provider_message_id,
            source_kind=source_kind,
            source_id=source_id,
            source_attempt_key=source_attempt_key,
            agency_id=agency_id,
            created_at=datetime.now(UTC),
        )
        .on_conflict_do_nothing()
    )
    matches = list(
        (
            await session.scalars(
                select(WhatsAppProviderMessageBindingModel).where(
                    or_(
                        and_(
                            WhatsAppProviderMessageBindingModel.provider_phone_number_id == account,
                            WhatsAppProviderMessageBindingModel.provider_message_id
                            == provider_message_id,
                        ),
                        and_(
                            WhatsAppProviderMessageBindingModel.source_kind == source_kind,
                            WhatsAppProviderMessageBindingModel.source_id == source_id,
                            WhatsAppProviderMessageBindingModel.source_attempt_key
                            == source_attempt_key,
                        ),
                    )
                )
            )
        ).all()
    )
    if len(matches) != 1:
        raise ProviderBindingConflict("Conflicting WhatsApp provider binding")
    binding = matches[0]
    if (
        binding.source_kind,
        binding.source_id,
        binding.source_attempt_key,
        binding.provider_message_id,
        binding.provider_phone_number_id,
    ) != (source_kind, source_id, source_attempt_key, provider_message_id, account):
        raise ProviderBindingConflict("Conflicting WhatsApp provider binding")
    return binding


async def bind_source_provider_message(
    session: AsyncSession,
    source: ReceiptSource,
    *,
    provider_phone_number_id: str | None,
) -> None:
    provider_id = source_provider_id(source)
    if provider_id is None:
        return
    kind, source_id, attempt_key = source_identity(source)
    await bind_provider_message(
        session,
        source_kind=kind,
        source_id=source_id,
        source_attempt_key=attempt_key,
        provider_phone_number_id=provider_phone_number_id,
        provider_message_id=provider_id,
        agency_id=source.agency_id,
    )


async def commit_private_provider_outcome(
    session: AsyncSession,
    delivery: DocumentWhatsAppDeliveryModel | PassengerQrWhatsAppDeliveryModel,
    *,
    provider_phone_number_id: str | None,
) -> None:
    """Retry persistence of a known result, never the external provider send."""
    kind, source_id, attempt_key = source_identity(delivery)
    provider_id, media_id, agency_id = (
        delivery.provider_message_id,
        delivery.provider_media_id,
        delivery.agency_id,
    )
    model = type(delivery)
    try:
        await bind_source_provider_message(
            session, delivery, provider_phone_number_id=provider_phone_number_id
        )
        await session.commit()
    except Exception:
        await session.rollback()
        if not provider_id:
            raise
        saved = cast(
            DocumentWhatsAppDeliveryModel | PassengerQrWhatsAppDeliveryModel | None,
            (
                await session.execute(select(model).where(model.id == source_id).with_for_update())
            ).scalar_one_or_none(),
        )
        if saved is not None and saved.send_batch_id == attempt_key:
            if saved.provider_message_id not in {None, provider_id}:
                raise ProviderBindingConflict("Provider result conflicts with current delivery")
            if saved.provider_message_id is None:
                saved.status = "submitted"
                saved.error_message = None
                saved.status_updated_at = saved.updated_at = datetime.now(UTC)
            saved.provider_message_id = provider_id
            saved.provider_media_id = media_id
        await bind_provider_message(
            session,
            source_kind=kind,
            source_id=source_id,
            source_attempt_key=attempt_key,
            provider_phone_number_id=provider_phone_number_id,
            provider_message_id=provider_id,
            agency_id=agency_id if saved is not None else None,
        )
        await session.commit()
