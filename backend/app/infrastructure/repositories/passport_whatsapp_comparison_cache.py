"""Short-lived exact-input reuse for one bounded update-dispatch slice."""

from __future__ import annotations

import asyncio
import copy
import uuid
from dataclasses import asdict

from app.application.use_cases.whatsapp.group_submission_matching import (
    RecipientForComparison,
    SubmissionForComparison,
    SubmissionMatchRow,
    compare_group_submissions,
)


class PassportWhatsAppComparisonCache:
    """Reuse only isolated, equal projections read under the current source locks.

    Store deep copies rather than ORM objects or revision timestamps. Comparing
    the complete domain projections includes nested JSON and the link's matching
    policy, so in-place edits, new ambiguity and resolution exclusions invalidate
    reuse. Ownership is one worker slice; nothing is global or persisted.
    """

    def __init__(self) -> None:
        self._inputs: dict[tuple[uuid.UUID, uuid.UUID], object] = {}
        self._rows: dict[tuple[uuid.UUID, uuid.UUID], list[SubmissionMatchRow]] = {}

    async def compare(
        self,
        *,
        agency_id: uuid.UUID,
        group_id: uuid.UUID,
        recipients: list[RecipientForComparison],
        submissions: list[SubmissionForComparison],
    ) -> list[SubmissionMatchRow]:
        scope = agency_id, group_id
        ordered_recipients = sorted(recipients, key=lambda row: str(row.id))
        ordered_submissions = sorted(submissions, key=lambda row: str(row.id))
        # asdict recursively copies nested containers. Private stored snapshots
        # never share mutable JSON with a later ORM refresh or caller.
        inputs = (
            [asdict(row) for row in ordered_recipients],
            [asdict(row) for row in ordered_submissions],
        )
        if self._inputs.get(scope) == inputs:
            return copy.deepcopy(self._rows[scope])
        rows, _counts = await asyncio.to_thread(
            compare_group_submissions, ordered_recipients, ordered_submissions
        )
        self._inputs[scope] = inputs
        self._rows[scope] = copy.deepcopy(rows)
        return rows
