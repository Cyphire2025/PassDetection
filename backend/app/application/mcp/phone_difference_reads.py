"""Compact phone comparisons using the dashboard's authoritative match decisions."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.credentials import utc
from app.application.mcp.read_context import MCPReadContext
from app.application.use_cases.passports.client_details_fields import saved_field_value
from app.application.use_cases.whatsapp.group_submission_matching import (
    normalize_matching_field_key,
    summarize_match_rows,
)
from app.domain.value_objects.phone_number import normalize_phone_number
from app.infrastructure.database.models import WhatsAppBroadcastRecipientModel
from app.infrastructure.repositories.sensitive_read_audit import record_sensitive_read

MAX_PAGE_BYTES = 24000


def compare_matched_phones(rows, submissions, recipients, broadcast_id):
    """Never create a new identity match or resolve an ambiguous submission party."""
    differences, compared, identical, missing, invalid = [], set(), 0, 0, 0
    selected = [row for row in rows if broadcast_id in row.broadcast_ids]
    for row in selected:
        if row.status != "submitted" or row.confidence != "high" or len(row.submission_ids) != 1:
            continue
        submission = submissions[row.submission_ids[0]]
        for recipient_id in row.recipient_ids:
            recipient = recipients.get(recipient_id)
            if recipient is None or recipient.broadcast_group_id != broadcast_id:
                continue
            pair = submission.id, recipient.id
            if pair in compared:
                continue
            compared.add(pair)
            submission_phone = submission.client_phone
            broadcast_phone = recipient.phone_number
            if not submission_phone or not submission_phone.strip() or not broadcast_phone or not broadcast_phone.strip():
                missing += 1
                continue
            normalized_submission = normalize_phone_number(submission_phone)
            normalized_broadcast = normalize_phone_number(broadcast_phone)
            if normalized_submission is None or normalized_broadcast is None:
                invalid += 1
                continue
            if normalized_submission == normalized_broadcast:
                identical += 1
                continue
            code, code_source = saved_field_value(submission, "staff_code")
            codes = {str(value) for key, value in (recipient.imported_fields or {}).items()
                if normalize_matching_field_key(key) == "staff_code" and value not in (None, "")}
            differences.append({
                "submission_id": str(submission.id), "recipient_id": str(recipient.id),
                "broadcast_id": str(broadcast_id), "submitted_name": submission.client_name,
                "broadcast_name": recipient.name, "staff_code": code,
                "staff_code_source": code_source,
                "broadcast_staff_code": next(iter(codes)) if len(codes) == 1 else None,
                "submission_phone": submission_phone, "broadcast_phone": broadcast_phone,
                "normalized_submission_phone": normalized_submission,
                "normalized_broadcast_phone": normalized_broadcast,
                "match_basis": row.match_basis, "match_confidence": row.confidence,
                "match_evidence_kinds": sorted({e.kind for e in row.match_evidence}),
            })
    differences.sort(key=lambda item: (item["submitted_name"].casefold(), item["submission_id"], item["recipient_id"]))
    return differences, {
        "canonical_match_counts": asdict(summarize_match_rows(selected)),
        "compared_match_pairs": len(compared), "same_phone_pairs": identical,
        "different_phone_pairs": len(differences), "missing_phone_pairs": missing,
        "invalid_phone_pairs": invalid,
        "unique_people_with_differences": len({item["submission_id"] for item in differences}),
        "excluded_ambiguous_match_rows": sum(row.status == "multiple_submissions" for row in selected),
        "excluded_review_match_rows": sum(row.status == "needs_review" or row.status == "submitted" and row.confidence != "high" for row in selected),
    }


def difference_page(items, *, offset, page_size):
    """Keep every returned comparison complete, and bound encoded UTF-8 size."""
    chosen = []
    for item in items[offset:offset + page_size]:
        candidate = [*chosen, item]
        if len(json.dumps(candidate, ensure_ascii=True, allow_nan=False).encode()) > MAX_PAGE_BYTES:
            if not chosen:
                raise ValueError("A comparison row exceeds the response bound; inspect its full dashboard details")
            break
        chosen = candidate
    following = offset + len(chosen)
    return chosen, following if following < len(items) else None


@dataclass(frozen=True)
class PhoneDifferenceSupport:
    """Reviewed canonical matching functions injected at the presentation boundary."""

    linked_names: Callable[..., Awaitable[Any]]
    matching_fields: Callable[..., Awaitable[Any]]
    load_rows: Callable[..., Awaitable[Any]]


class MCPPhoneDifferenceReadService(MCPReadContext):
    def __init__(self, session: AsyncSession, *, cursor_secret: str, support: PhoneDifferenceSupport):
        super().__init__(session, cursor_secret=cursor_secret, namespace="mcp-phone-differences-v1")
        self.support = support

    async def read(self, *, user_id: UUID, group_id: UUID, broadcast_id: UUID | None = None,
        agency_id: UUID | None = None, offset: int = 0, page_size: int = 50,
        snapshot_revision: str | None = None) -> dict[str, Any]:
        if type(offset) is not int or not 0 <= offset <= 100000:
            raise ValueError("Comparison offset must be between 0 and 100000")
        actor = await self._actor(user_id, page_size)
        await self._agency(agency_id)
        group = await self._group(actor, group_id, agency_id, include_deleted=False)
        if group.status == "archived":
            raise ValueError("Choose an active client group")
        linked = await self.support.linked_names(self.session, group_id=group.id, agency_id=group.agency_id)
        if broadcast_id is None:
            if len(linked) != 1:
                raise ValueError("Choose one linked broadcast explicitly when there is not exactly one")
            broadcast_id = next(iter(linked))
        if broadcast_id not in linked:
            raise ValueError("The broadcast is not linked to this client group")
        fields = await self.support.matching_fields(self.session, group_id=group.id, agency_id=group.agency_id)
        rows, submissions = await self.support.load_rows(self.session, group=group,
            linked_broadcasts=linked, matching_fields_by_broadcast=fields)
        recipient_rows = list((await self.session.scalars(select(WhatsAppBroadcastRecipientModel).where(
            WhatsAppBroadcastRecipientModel.broadcast_group_id == broadcast_id,
            WhatsAppBroadcastRecipientModel.agency_id == group.agency_id,
            WhatsAppBroadcastRecipientModel.removed_at.is_(None),
            WhatsAppBroadcastRecipientModel.suppressed_by_roster_resolution_id.is_(None),
        ))).all())
        recipients = {row.id: row for row in recipient_rows}
        items, counts = compare_matched_phones(rows, submissions, recipients, broadcast_id)
        counts.update(office_visible_submission_records=len(submissions), active_broadcast_entries=len(recipients))
        # The fence includes all loaded inputs, not just the nine/small difference rows.
        identity = [
            sorted((str(s.id), utc(s.updated_at).isoformat(), s.client_phone, s.client_name) for s in submissions.values()),
            sorted((str(r.id), r.phone_number, r.normalized_phone_number, r.name, r.imported_fields) for r in recipient_rows),
            [asdict(row) for row in sorted(rows, key=lambda r: (r.status,
                tuple(map(str, r.recipient_ids)), tuple(map(str, r.submission_ids))))], items, counts,
        ]
        fingerprint = hashlib.sha256(json.dumps(identity, default=str, sort_keys=True, ensure_ascii=True).encode()).hexdigest()
        if offset and snapshot_revision is None:
            raise ValueError("Continue with the previous response's snapshot_revision")
        if snapshot_revision is not None and snapshot_revision != fingerprint:
            raise ValueError("The matching data changed; restart this comparison")
        page, next_offset = difference_page(items, offset=offset, page_size=page_size)
        await record_sensitive_read(self.session, user=actor, kind="group_list",
            agency_id=group.agency_id, entity_id=group.id, count=len(page))
        return {"group_id": str(group.id), "group_name": group.name, "agency_id": str(group.agency_id),
            "broadcast_id": str(broadcast_id), "broadcast_name": linked[broadcast_id],
            "items": page, "counts": counts, "total": len(items), "offset": offset,
            "page_size": page_size, "has_more": next_offset is not None, "next_offset": next_offset,
            "snapshot_revision": fingerprint, "completeness": "partial" if next_offset is not None else "complete",
            "content_trust": "untrusted_business_data", "consistency": "live_multi_query_restart_if_inputs_change",
            "notice": "Only high-confidence submitted matches with exactly one submission are compared. Rows are submission/recipient pairs, not necessarily unique people. Ambiguous, review and manual replacement/rejection rows are excluded and counted by canonical status. Missing/invalid phones are counted separately. Formatting/country-code differences are normalized. This neither establishes which number is correct nor edits records, prepares messages or creates an export."}
