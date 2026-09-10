"""Identity-strength policy for sensitive WhatsApp delivery destinations."""

from __future__ import annotations

import uuid

from app.application.use_cases.whatsapp.group_submission_matching import (
    SubmissionMatchRow,
)

PRIVATE_DELIVERY_EVIDENCE_KINDS = frozenset(
    {
        "phone",
        "phone_number",
        "email",
        "passport_number",
        "staff_code",
    }
)


def has_private_delivery_identity_evidence(
    row: SubmissionMatchRow,
    *,
    submission_id: uuid.UUID,
) -> bool:
    """Require legacy-strength evidence for a specific matched submission."""

    return any(
        evidence.submission_id == submission_id
        and evidence.kind in PRIVATE_DELIVERY_EVIDENCE_KINDS
        and getattr(evidence, "private_identity_confirmed", None) is not False
        for evidence in row.match_evidence
    )


def is_private_delivery_match(row: SubmissionMatchRow) -> bool:
    """Accept only one-to-one matches backed by private-grade identity evidence."""

    return (
        row.status == "submitted"
        and len(row.submission_ids) == 1
        and has_private_delivery_identity_evidence(
            row,
            submission_id=row.submission_ids[0],
        )
    )
