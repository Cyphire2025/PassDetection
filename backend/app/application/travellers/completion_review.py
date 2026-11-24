"""Bind current returning-traveller authority to the exact displayed review."""

from __future__ import annotations

import hmac
import uuid
from typing import NamedTuple

from app.application.platform_policies import PlatformPolicies
from app.application.travellers.claims import ReturningClaims
from app.application.travellers.errors import ReuseError, ReuseReason
from app.application.travellers.history import (
    ReviewContext,
    project_history,
    review_context,
    review_version,
)
from app.application.travellers.owned_extraction import owned_extraction_candidate
from app.infrastructure.repositories.platform_policy_repository import PlatformPolicyRepository


class ReuseReview(NamedTuple):
    context: ReviewContext
    policies: PlatformPolicies
    review: dict[str, object]


async def review_reuse_completion(
    service: ReturningClaims,
    token: str,
    *,
    requirements_version: str,
    expected_review_version: str,
    owned_source_id: uuid.UUID | None,
    owned_source_revision: int | None,
    upload_session_id: str | None,
) -> ReuseReview:
    """Keep the original authority transaction and validation/error order."""
    context = await review_context(service, token)
    grant, scope, person, passport, revision, assets = context
    if owned_source_id is not None:
        if (
            owned_source_revision is None
            or not upload_session_id
            or await owned_extraction_candidate(
                service.session,
                group=scope.group,
                source_submission_id=owned_source_id,
                expected_extraction_revision=owned_source_revision,
                upload_session_id=upload_session_id,
                crypto=service.crypto,
                lock_source=True,
            )
            != person.id
        ):
            raise ReuseError(ReuseReason.REVISION_CONFLICT)
    policies = await PlatformPolicyRepository(service.session).load()
    review = await project_history(service, context, policies)
    if "participation:submit" not in grant.allowed_actions:
        raise ReuseError(ReuseReason.UNAVAILABLE)
    if review["question_version"] != requirements_version or not hmac.compare_digest(
        expected_review_version,
        review_version(service, context, policies),
    ):
        raise ReuseError(ReuseReason.REVISION_CONFLICT)
    return ReuseReview(context, policies, review)
