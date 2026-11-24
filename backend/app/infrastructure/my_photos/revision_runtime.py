"""Stable gallery publication imports and call-time refresh dispatch."""

from __future__ import annotations

import uuid

from app.core.config.settings import Settings
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.my_photos import revision_refresh as _refresh
from app.infrastructure.my_photos.revision_contracts import (
    RefreshFanoutResult as RefreshFanoutResult,
)
from app.infrastructure.my_photos.revision_contracts import RefreshFanoutState as RefreshFanoutState
from app.infrastructure.my_photos.revision_contracts import RevisionContext
from app.infrastructure.my_photos.revision_policy import (
    _checkpoint_uuid as _checkpoint_uuid,
)
from app.infrastructure.my_photos.revision_policy import (
    _complete_job as _complete_job,
)
from app.infrastructure.my_photos.revision_policy import (
    _fail_job as _fail_job,
)
from app.infrastructure.my_photos.revision_policy import (
    _refresh_claim_current as _refresh_claim_current,
)
from app.infrastructure.my_photos.revision_publication import (
    publish_gallery_revision as publish_gallery_revision,
)


async def execute_refresh_fanout(
    *, job_id: uuid.UUID, lease_owner: str, settings: Settings
) -> RefreshFanoutResult:
    """Create current-revision search jobs without materializing all passengers."""
    return await _refresh.execute_refresh_fanout(
        RevisionContext(AsyncSessionFactory),
        job_id=job_id,
        lease_owner=lease_owner,
        settings=settings,
    )


__all__ = ["RefreshFanoutResult", "execute_refresh_fanout", "publish_gallery_revision"]
