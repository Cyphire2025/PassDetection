"""Persistence adapter for global operational policies."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.platform_policies import (
    PLATFORM_SETTINGS_KEY,
    PlatformPolicies,
)
from app.infrastructure.database.models import PlatformSettingModel


class PlatformPolicyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def load(self) -> PlatformPolicies:
        result = await self._session.execute(
            select(PlatformSettingModel.value).where(
                PlatformSettingModel.key == PLATFORM_SETTINGS_KEY
            )
        )
        value = result.scalar_one_or_none()
        return PlatformPolicies.from_mapping(value)
