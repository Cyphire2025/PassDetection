"""Bounded, owner-authorized live context for travel email analysis."""

from __future__ import annotations

import hashlib
import json
import re
import string
import uuid
from dataclasses import dataclass
from datetime import UTC
from difflib import SequenceMatcher

from sqlalchemy import and_, case, false, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.security.authorization_policy import AuthorizationPolicy
from app.domain.entities.entities import UserRole
from app.domain.value_objects.email_ai_analysis import (
    CandidateEntityType,
    EmailAnalysisRequest,
    VisibleEmailCandidate,
)
from app.infrastructure.database.email_models import (
    EmailArtifactModel,
    EmailMessageModel,
)
from app.infrastructure.database.models import (
    ClientGroupModel,
    PassportSubmissionModel,
)
from app.infrastructure.repositories.user_repository import UserRepository

_REQUEST_MAX_BODY_CHARS = 16_000
_REQUEST_MAX_CANDIDATES = 24
_GROUP_NAME_MAX_WORDS = 8
_FUZZY_GROUP_SCAN_LIMIT = 240
_FUZZY_GROUP_MIN_SCORE = 0.78
_GROUP_NAME_SEPARATORS = (
    *string.punctuation,
    "–",
    "—",
    "−",
    "‐",
    "‑",
    "‒",
    "·",
    "•",
    "“",
    "”",
    "‘",
    "’",
    "…",
    "\t",
    "\r",
    "\n",
    "\v",
    "\f",
    "\u00a0",
)


@dataclass(frozen=True)
class EmailAiContext:
    request: EmailAnalysisRequest
    input_hash: str
    aliases: dict[str, tuple[str, uuid.UUID]]
    manifest: dict[str, object]


async def load_email_ai_context(
    session: AsyncSession,
    *,
    message: EmailMessageModel,
    agency_id: uuid.UUID,
    owner_user_id: uuid.UUID,
    connected_account_email: str,
    timezone_name: str,
    max_input_chars: int,
    max_candidates: int,
) -> EmailAiContext | None:
    """Load only live records the mailbox owner may already view."""

    if message.agency_id != agency_id or message.owner_user_id != owner_user_id:
        return None

    owner = await UserRepository(session).get_by_id(owner_user_id)
    if (
        owner is None
        or not owner.is_active
        or (owner.role != UserRole.SUPER_ADMIN and owner.agency_id != agency_id)
    ):
        return None

    bounded_candidates = min(max_candidates, _REQUEST_MAX_CANDIDATES)
    group_limit = min(12, bounded_candidates)
    normalized_email_group_windows = _normalized_email_group_windows(
        subject=(message.subject or "")[:500],
        body=(message.body_excerpt or "")[
            : min(max_input_chars, _REQUEST_MAX_BODY_CHARS)
        ],
    )
    group_match_predicates: list[object] = []
    if message.group_id is not None:
        group_match_predicates.append(ClientGroupModel.id == message.group_id)
    if normalized_email_group_windows:
        normalized_group_name = _normalized_group_name_expression()
        normalized_group_word_count = (
            func.length(normalized_group_name)
            - func.length(func.replace(normalized_group_name, " ", ""))
            + 1
        )
        window_match_predicates = [
            literal(f" {window} ").like(literal("% ") + normalized_group_name + literal(" %"))
            for window in normalized_email_group_windows
        ]
        group_match_predicates.append(
            and_(
                func.length(normalized_group_name) >= 3,
                normalized_group_word_count <= _GROUP_NAME_MAX_WORDS,
                or_(*window_match_predicates),
            )
        )
    preferred_group_order = case(
        (ClientGroupModel.id == message.group_id, 0),
        else_=1,
    )
    groups_statement = (
        select(ClientGroupModel)
        .where(
            ClientGroupModel.agency_id == agency_id,
            ClientGroupModel.status.notin_({"archived", "deleted"}),
            (or_(*group_match_predicates) if group_match_predicates else false()),
        )
        .order_by(
            preferred_group_order,
            ClientGroupModel.travel_date.asc(),
            ClientGroupModel.created_at.desc(),
        )
        .limit(group_limit)
    )
    groups_result = await session.execute(
        AuthorizationPolicy.apply_group_visibility_scope(groups_statement, owner)
    )
    groups = list(groups_result.scalars().all())
    if (
        normalized_email_group_windows
        and len(groups) < group_limit
    ):
        exact_group_ids = [group.id for group in groups]
        fuzzy_statement = (
            select(ClientGroupModel)
            .where(
                ClientGroupModel.agency_id == agency_id,
                ClientGroupModel.status.notin_({"archived", "deleted"}),
            )
            .order_by(
                ClientGroupModel.travel_date.asc(),
                ClientGroupModel.created_at.desc(),
                ClientGroupModel.id.asc(),
            )
            .limit(_FUZZY_GROUP_SCAN_LIMIT)
        )
        if exact_group_ids:
            fuzzy_statement = fuzzy_statement.where(
                ClientGroupModel.id.notin_(exact_group_ids)
            )
        fuzzy_result = await session.execute(
            AuthorizationPolicy.apply_group_visibility_scope(
                fuzzy_statement,
                owner,
            )
        )
        scored_groups = [
            (
                _fuzzy_group_name_score(
                    group.name,
                    normalized_email_group_windows,
                ),
                group,
            )
            for group in fuzzy_result.scalars().all()
        ]
        scored_groups = [
            (score, group)
            for score, group in scored_groups
            if score >= _FUZZY_GROUP_MIN_SCORE
        ]
        scored_groups.sort(
            key=lambda item: (-item[0], str(item[1].id))
        )
        groups.extend(
            group
            for _, group in scored_groups[
                : max(0, group_limit - len(groups))
            ]
        )

    candidates: list[VisibleEmailCandidate] = []
    aliases: dict[str, tuple[str, uuid.UUID]] = {}
    group_aliases: dict[uuid.UUID, str] = {}
    for index, group in enumerate(groups, start=1):
        alias = f"group_{index:03d}"
        group_aliases[group.id] = alias
        aliases[alias] = ("group", group.id)
        facts = [_fact("name", group.name), _fact("status", group.status)]
        if group.destination:
            facts.append(_fact("destination", group.destination))
        if group.travel_date:
            facts.append(_fact("travel date", group.travel_date.isoformat()))
        if group.return_date:
            facts.append(_fact("return date", group.return_date.isoformat()))
        candidates.append(
            VisibleEmailCandidate(
                alias=alias,
                entity_type=CandidateEntityType.GROUP,
                safe_facts=facts,
            )
        )

    passenger_slots = max(0, bounded_candidates - len(candidates))
    deterministic_group_id = (
        message.group_id
        if message.group_id is not None and message.group_id in group_aliases
        else None
    )
    if passenger_slots and deterministic_group_id is not None:
        normalized_passenger_name = _normalized_name_expression(
            PassportSubmissionModel.client_name
        )
        normalized_passenger_word_count = (
            func.length(normalized_passenger_name)
            - func.length(
                func.replace(normalized_passenger_name, " ", "")
            )
            + 1
        )
        passenger_window_predicates = [
            literal(f" {window} ").like(
                literal("% ")
                + normalized_passenger_name
                + literal(" %")
            )
            for window in normalized_email_group_windows
        ]
        passenger_name_match = (
            and_(
                func.length(normalized_passenger_name) >= 3,
                normalized_passenger_word_count
                <= _GROUP_NAME_MAX_WORDS,
                or_(*passenger_window_predicates),
            )
            if passenger_window_predicates
            else false()
        )
        passenger_statement = (
            select(
                PassportSubmissionModel.id,
                PassportSubmissionModel.group_id,
                PassportSubmissionModel.client_name,
                PassportSubmissionModel.status,
            )
            .where(
                PassportSubmissionModel.agency_id == agency_id,
                PassportSubmissionModel.group_id == deterministic_group_id,
                PassportSubmissionModel.status != "failed",
            )
            .order_by(
                case((passenger_name_match, 0), else_=1),
                PassportSubmissionModel.updated_at.desc(),
                PassportSubmissionModel.id.asc(),
            )
            .limit(passenger_slots)
        )
        passenger_result = await session.execute(
            AuthorizationPolicy.apply_passport_visibility_scope(
                passenger_statement,
                owner,
            )
        )
        for index, row in enumerate(passenger_result.all(), start=1):
            alias = f"passenger_{index:03d}"
            aliases[alias] = ("passenger", row.id)
            candidates.append(
                VisibleEmailCandidate(
                    alias=alias,
                    entity_type=CandidateEntityType.PASSENGER,
                    safe_facts=[
                        _fact("name", row.client_name),
                        _fact("group alias", group_aliases[row.group_id]),
                        _fact("workflow status", row.status),
                    ],
                )
            )

    attachment_result = await session.execute(
        select(EmailArtifactModel.filename)
        .where(
            EmailArtifactModel.message_id == message.id,
            EmailArtifactModel.agency_id == agency_id,
            EmailArtifactModel.owner_user_id == owner_user_id,
            EmailArtifactModel.kind == "attachment",
        )
        .order_by(EmailArtifactModel.created_at.asc())
        .limit(20)
    )
    attachment_filenames = [
        filename[:180]
        for filename in attachment_result.scalars().all()
        if isinstance(filename, str) and filename.strip()
    ]
    received_at = message.received_at
    if received_at.tzinfo is None:
        received_at = received_at.replace(tzinfo=UTC)
    request = EmailAnalysisRequest(
        subject=(message.subject or "")[:500],
        body_text=(message.body_excerpt or "")[: min(max_input_chars, _REQUEST_MAX_BODY_CHARS)],
        attachment_filenames=attachment_filenames,
        sender_display_name=_safe_display_name(message.sender_name),
        sender_domain=_address_domain(message.sender_address),
        recipient_domains=_recipient_domains(message.recipients_json),
        connected_account_domain=_address_domain(connected_account_email),
        received_at=received_at,
        timezone=timezone_name,
        visible_candidates=candidates,
    )
    manifest: dict[str, object] = {
        "candidate_count": len(candidates),
        "identity_context": {
            "sender_display_name_provided": bool(request.sender_display_name),
            "sender_domain_provided": bool(request.sender_domain),
            "recipient_domain_count": len(request.recipient_domains),
            "connected_account_domain_provided": bool(request.connected_account_domain),
        },
        "aliases": {
            alias: {"entity_type": entity_type, "entity_id": str(entity_id)}
            for alias, (entity_type, entity_id) in aliases.items()
        },
    }
    input_hash = hashlib.sha256(
        json.dumps(
            {
                "provider_message_id": message.provider_message_id,
                "request": request.model_dump(mode="json"),
                "manifest": manifest,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return EmailAiContext(
        request=request,
        input_hash=input_hash,
        aliases=aliases,
        manifest=manifest,
    )


def _fact(label: str, value: object) -> str:
    return f"{label}: {' '.join(str(value).split())}"[:160]


def _safe_display_name(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.split())[:160]
    return normalized or None


def _address_domain(value: str | None) -> str | None:
    if not isinstance(value, str) or value.count("@") != 1:
        return None
    domain = value.rsplit("@", 1)[1].strip().strip(".").casefold()
    try:
        ascii_domain = domain.encode("idna").decode("ascii")
    except UnicodeError:
        return None
    if (
        not ascii_domain
        or len(ascii_domain) > 253
        or ".." in ascii_domain
        or any(
            character not in "abcdefghijklmnopqrstuvwxyz0123456789.-" for character in ascii_domain
        )
    ):
        return None
    return ascii_domain


def _recipient_domains(
    recipients: object,
) -> list[str]:
    if not isinstance(recipients, list):
        return []
    domains: list[str] = []
    seen: set[str] = set()
    for recipient in recipients[:50]:
        if not isinstance(recipient, dict):
            continue
        address = recipient.get("address")
        domain = _address_domain(address if isinstance(address, str) else None)
        if domain is None or domain in seen:
            continue
        seen.add(domain)
        domains.append(domain)
        if len(domains) >= 20:
            break
    return domains


def _normalized_email_group_windows(
    *,
    subject: str,
    body: str,
) -> tuple[str, ...]:
    """Return the same bounded subject/body text used for provider input."""

    windows: list[str] = []
    subject_words = re.findall(r"[a-z0-9]+", subject.casefold())
    body_words = re.findall(r"[a-z0-9]+", body.casefold())

    subject_window = " ".join(subject_words)
    if subject_window:
        windows.append(subject_window)

    body_window = " ".join(body_words)
    if body_window and body_window not in windows:
        windows.append(body_window)

    return tuple(windows)


def _normalized_group_name_expression():  # type: ignore[no-untyped-def]
    """Normalize stored group names with portable SQL string functions."""

    return _normalized_name_expression(ClientGroupModel.name)


def _normalized_name_expression(column):  # type: ignore[no-untyped-def]
    normalized = func.lower(column)
    for separator in _GROUP_NAME_SEPARATORS:
        normalized = func.replace(normalized, separator, " ")
    # Eight passes collapse any separator run within the 255-character column.
    for _ in range(8):
        normalized = func.replace(normalized, "  ", " ")
    return func.trim(normalized)


def _fuzzy_group_name_score(
    group_name: str,
    email_windows: tuple[str, ...],
) -> float:
    """Score bounded spelling/abbreviation matches for candidate retrieval."""

    group_tokens = re.findall(r"[a-z0-9]+", group_name.casefold())[
        :_GROUP_NAME_MAX_WORDS
    ]
    email_tokens = [
        token
        for window in email_windows
        for token in window.split()
    ]
    if not group_tokens or not email_tokens:
        return 0.0

    group_text = " ".join(group_tokens)
    token_count = len(group_tokens)
    full_score = 0.0
    for width in {
        max(1, token_count - 1),
        token_count,
        token_count + 1,
    }:
        for index in range(max(0, len(email_tokens) - width + 1)):
            phrase = " ".join(email_tokens[index : index + width])
            full_score = max(
                full_score,
                SequenceMatcher(
                    None,
                    group_text,
                    phrase,
                    autojunk=False,
                ).ratio(),
            )

    token_scores = [
        max(
            SequenceMatcher(
                None,
                group_token,
                email_token,
                autojunk=False,
            ).ratio()
            for email_token in email_tokens
        )
        for group_token in group_tokens
    ]
    token_score = sum(token_scores) / len(token_scores)
    spelling_score = (
        max(full_score, token_score)
        if min(token_scores) >= 0.72
        else 0.0
    )

    acronym = "".join(
        token if token.isdigit() else token[0]
        for token in group_tokens
    )
    compact_email = "".join(email_tokens)
    acronym_score = (
        0.9
        if len(group_tokens) >= 2
        and len(acronym) >= 3
        and acronym in compact_email
        else 0.0
    )
    abbreviation_score = _ordered_abbreviation_score(
        group_tokens,
        email_tokens,
    )
    if len(group_tokens) == 1 and full_score < 0.92:
        spelling_score = 0.0
    return max(spelling_score, acronym_score, abbreviation_score)


def _ordered_abbreviation_score(
    group_tokens: list[str],
    email_tokens: list[str],
) -> float:
    """Recognize a complete ordered short form without partial-name guesses."""

    if len(group_tokens) < 2 or len(email_tokens) < len(group_tokens):
        return 0.0
    for start in range(len(email_tokens) - len(group_tokens) + 1):
        short_tokens = email_tokens[start : start + len(group_tokens)]
        if all(
            _abbreviation_token_matches(group_token, short_token)
            for group_token, short_token in zip(
                group_tokens,
                short_tokens,
                strict=True,
            )
        ):
            return 0.88
    return 0.0


def _abbreviation_token_matches(
    group_token: str,
    short_token: str,
) -> bool:
    if group_token == short_token:
        return True
    if group_token.isdigit() or short_token.isdigit():
        return bool(
            group_token.isdigit()
            and short_token.isdigit()
            and len(group_token) == 4
            and len(short_token) == 2
            and group_token.endswith(short_token)
        )
    if len(short_token) >= 3:
        return group_token.startswith(short_token)
    if len(short_token) != 2 or len(group_token) < 4:
        return False
    first_index = group_token.find(short_token[0])
    second_index = group_token.find(short_token[1], first_index + 1)
    return first_index == 0 and second_index > first_index
