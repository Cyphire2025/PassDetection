from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.value_objects.email_ai_analysis import CandidateEntityType
from app.infrastructure.database.email_models import (
    EmailArtifactModel,
    EmailConnectionModel,
    EmailMessageModel,
)
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    ManagerGroupAccessModel,
    PassportSubmissionModel,
    UserModel,
)
from app.infrastructure.email.ai_context import load_email_ai_context

NOW = datetime(2026, 7, 30, 8, 0, tzinfo=UTC)


def _user(
    *,
    email: str,
    agency_id: uuid.UUID | None,
    role: str = "agency_staff",
    is_active: bool = True,
) -> UserModel:
    return UserModel(
        id=uuid.uuid4(),
        email=email,
        hashed_password="not-used",
        full_name=email.split("@", 1)[0].replace("-", " ").title(),
        role=role,
        agency_id=agency_id,
        is_active=is_active,
    )


def _group(
    *,
    agency_id: uuid.UUID,
    name: str,
    creator_id: uuid.UUID,
    status: str = "active",
) -> ClientGroupModel:
    return ClientGroupModel(
        id=uuid.uuid4(),
        agency_id=agency_id,
        name=name,
        token=f"context-{uuid.uuid4().hex}",
        status=status,
        created_by_user_id=creator_id,
    )


def _passenger(
    *,
    group: ClientGroupModel,
    name: str,
    status: str,
) -> PassportSubmissionModel:
    return PassportSubmissionModel(
        id=uuid.uuid4(),
        group_id=group.id,
        agency_id=group.agency_id,
        client_name=name,
        image_s3_key=f"context/{uuid.uuid4().hex}.jpg",
        status=status,
        created_at=NOW,
        updated_at=NOW,
    )


def _connection(
    *,
    agency_id: uuid.UUID,
    owner_id: uuid.UUID,
    account: str,
) -> EmailConnectionModel:
    return EmailConnectionModel(
        id=uuid.uuid4(),
        agency_id=agency_id,
        owner_user_id=owner_id,
        provider="gmail",
        provider_account_id=f"context-{uuid.uuid4().hex}",
        email_address=account,
        status="active",
        created_by_user_id=owner_id,
    )


def _message(
    *,
    connection: EmailConnectionModel,
    provider_message_id: str,
    subject: str,
    body_excerpt: str,
    group_id: uuid.UUID | None,
) -> EmailMessageModel:
    return EmailMessageModel(
        id=uuid.uuid4(),
        agency_id=connection.agency_id,
        owner_user_id=connection.owner_user_id,
        connection_id=connection.id,
        provider_message_id=provider_message_id,
        sender_address="supplier@partner.example",
        sender_name="Trusted Supplier",
        recipients_json=[{"address": connection.email_address}],
        subject=subject,
        body_excerpt=body_excerpt,
        received_at=NOW,
        group_id=group_id,
    )


def _artifact(
    *,
    message: EmailMessageModel,
    filename: str,
    kind: str = "attachment",
) -> EmailArtifactModel:
    return EmailArtifactModel(
        id=uuid.uuid4(),
        agency_id=message.agency_id,
        owner_user_id=message.owner_user_id,
        message_id=message.id,
        provider_artifact_id=f"context-{uuid.uuid4().hex}",
        kind=kind,
        filename=filename,
    )


async def _load(
    db_session: AsyncSession,
    *,
    message: EmailMessageModel,
    agency_id: uuid.UUID,
    owner_user_id: uuid.UUID,
    max_candidates: int = 24,
):
    return await load_email_ai_context(
        db_session,
        message=message,
        agency_id=agency_id,
        owner_user_id=owner_user_id,
        connected_account_email="owner@example.test",
        timezone_name="Asia/Calcutta",
        max_input_chars=8_000,
        max_candidates=max_candidates,
    )


@pytest.mark.asyncio
async def test_deterministic_group_context_is_owner_authorized_and_isolated(
    db_session: AsyncSession,
) -> None:
    agency = AgencyModel(
        id=uuid.uuid4(),
        name="Context Agency",
        email="context-agency@example.test",
    )
    other_agency = AgencyModel(
        id=uuid.uuid4(),
        name="Other Context Agency",
        email="other-context-agency@example.test",
    )
    owner = _user(
        email="owner@example.test",
        agency_id=agency.id,
    )
    same_agency_creator = _user(
        email="same-agency-creator@example.test",
        agency_id=agency.id,
    )
    other_agency_owner = _user(
        email="other-agency-owner@example.test",
        agency_id=other_agency.id,
    )
    db_session.add_all([agency, other_agency, owner, same_agency_creator, other_agency_owner])
    await db_session.flush()

    assigned_group = _group(
        agency_id=agency.id,
        name="Assigned Expedition",
        creator_id=same_agency_creator.id,
    )
    unauthorized_group = _group(
        agency_id=agency.id,
        name="Unauthorized Summit",
        creator_id=same_agency_creator.id,
    )
    archived_owned_group = _group(
        agency_id=agency.id,
        name="Archived Retreat",
        creator_id=owner.id,
        status="archived",
    )
    other_agency_group = _group(
        agency_id=other_agency.id,
        name="Cross Tenant Trek",
        creator_id=other_agency_owner.id,
    )
    db_session.add_all(
        [
            assigned_group,
            unauthorized_group,
            archived_owned_group,
            other_agency_group,
        ]
    )
    await db_session.flush()
    db_session.add(
        ManagerGroupAccessModel(
            manager_id=owner.id,
            group_id=assigned_group.id,
            agency_id=agency.id,
        )
    )

    visible_passenger = _passenger(
        group=assigned_group,
        name="Visible Passenger",
        status="confirmed",
    )
    failed_passenger = _passenger(
        group=assigned_group,
        name="Failed Passenger",
        status="failed",
    )
    unauthorized_passenger = _passenger(
        group=unauthorized_group,
        name="Unauthorized Passenger",
        status="submitted",
    )
    other_agency_passenger = _passenger(
        group=other_agency_group,
        name="Other Agency Passenger",
        status="submitted",
    )
    db_session.add_all(
        [
            visible_passenger,
            failed_passenger,
            unauthorized_passenger,
            other_agency_passenger,
        ]
    )

    connection = _connection(
        agency_id=agency.id,
        owner_id=owner.id,
        account="owner@example.test",
    )
    other_owner_connection = _connection(
        agency_id=agency.id,
        owner_id=same_agency_creator.id,
        account="same-agency-creator@example.test",
    )
    other_agency_connection = _connection(
        agency_id=other_agency.id,
        owner_id=other_agency_owner.id,
        account="other-agency-owner@example.test",
    )
    db_session.add_all([connection, other_owner_connection, other_agency_connection])
    await db_session.flush()
    message = _message(
        connection=connection,
        provider_message_id="deterministic-owner-message",
        subject="Documents for Unauthorized Summit and Archived Retreat",
        body_excerpt="Cross Tenant Trek is also mentioned.",
        group_id=assigned_group.id,
    )
    other_owner_message = _message(
        connection=other_owner_connection,
        provider_message_id="same-agency-other-owner-message",
        subject="Private attachment",
        body_excerpt="This belongs to another mailbox owner.",
        group_id=unauthorized_group.id,
    )
    other_agency_message = _message(
        connection=other_agency_connection,
        provider_message_id="other-agency-message",
        subject="Other tenant attachment",
        body_excerpt="This belongs to another agency.",
        group_id=other_agency_group.id,
    )
    db_session.add_all([message, other_owner_message, other_agency_message])
    await db_session.flush()
    db_session.add_all(
        [
            _artifact(message=message, filename="owner-visible.pdf"),
            _artifact(
                message=message,
                filename="owner-link-secret.pdf",
                kind="direct_link",
            ),
            _artifact(
                message=other_owner_message,
                filename="same-agency-other-owner-secret.pdf",
            ),
            _artifact(
                message=other_agency_message,
                filename="other-agency-secret.pdf",
            ),
        ]
    )
    await db_session.flush()

    context = await _load(
        db_session,
        message=message,
        agency_id=agency.id,
        owner_user_id=owner.id,
    )

    assert context is not None
    assert context.request.attachment_filenames == ["owner-visible.pdf"]
    assert [candidate.entity_type for candidate in context.request.visible_candidates] == [
        CandidateEntityType.GROUP,
        CandidateEntityType.PASSENGER,
    ]
    assert set(context.aliases.values()) == {
        ("group", assigned_group.id),
        ("passenger", visible_passenger.id),
    }
    all_safe_facts = {
        fact for candidate in context.request.visible_candidates for fact in candidate.safe_facts
    }
    assert "name: Assigned Expedition" in all_safe_facts
    assert "name: Visible Passenger" in all_safe_facts
    assert "name: Unauthorized Summit" not in all_safe_facts
    assert "name: Archived Retreat" not in all_safe_facts
    assert "name: Cross Tenant Trek" not in all_safe_facts
    assert "name: Failed Passenger" not in all_safe_facts
    assert "name: Unauthorized Passenger" not in all_safe_facts
    assert "name: Other Agency Passenger" not in all_safe_facts

    repeated_context = await _load(
        db_session,
        message=message,
        agency_id=agency.id,
        owner_user_id=owner.id,
    )
    assert repeated_context is not None
    assert repeated_context.input_hash == context.input_hash
    assert repeated_context.manifest == context.manifest


@pytest.mark.asyncio
async def test_exact_group_name_match_never_loads_passengers_without_group_id(
    db_session: AsyncSession,
) -> None:
    agency = AgencyModel(
        id=uuid.uuid4(),
        name="Name Match Agency",
        email="name-match-agency@example.test",
    )
    owner = _user(
        email="name-match-owner@example.test",
        agency_id=agency.id,
    )
    other_user = _user(
        email="name-match-other@example.test",
        agency_id=agency.id,
    )
    db_session.add_all([agency, owner, other_user])
    await db_session.flush()
    visible_group = _group(
        agency_id=agency.id,
        name="Alpine Discovery",
        creator_id=owner.id,
    )
    unauthorized_group = _group(
        agency_id=agency.id,
        name="Private Alpine",
        creator_id=other_user.id,
    )
    db_session.add_all([visible_group, unauthorized_group])
    await db_session.flush()
    visible_passenger = _passenger(
        group=visible_group,
        name="Name Match Passenger",
        status="confirmed",
    )
    unauthorized_passenger = _passenger(
        group=unauthorized_group,
        name="Private Passenger",
        status="confirmed",
    )
    db_session.add_all([visible_passenger, unauthorized_passenger])
    connection = _connection(
        agency_id=agency.id,
        owner_id=owner.id,
        account="name-match-owner@example.test",
    )
    db_session.add(connection)
    await db_session.flush()
    message = _message(
        connection=connection,
        provider_message_id="name-only-message",
        subject="Update for Alpine Discovery",
        body_excerpt="Private Alpine is also mentioned.",
        group_id=None,
    )
    db_session.add(message)
    await db_session.flush()

    context = await _load(
        db_session,
        message=message,
        agency_id=agency.id,
        owner_user_id=owner.id,
    )

    assert context is not None
    assert list(context.aliases.values()) == [("group", visible_group.id)]
    assert [candidate.entity_type for candidate in context.request.visible_candidates] == [
        CandidateEntityType.GROUP
    ]
    assert context.request.visible_candidates[0].safe_facts[0] == ("name: Alpine Discovery")
    assert all(
        "Name Match Passenger" not in fact and "Private Passenger" not in fact
        for candidate in context.request.visible_candidates
        for fact in candidate.safe_facts
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("prefix_filler_count", "suffix_filler_count", "combined_word_count"),
    [
        pytest.param(195, 0, 200, id="at-combined-200-word-boundary"),
        pytest.param(196, 0, 201, id="one-word-over-combined-boundary"),
        pytest.param(150, 150, 305, id="middle-of-bounded-excerpt"),
    ],
)
async def test_long_forwarded_email_matches_normalized_four_word_group_name(
    db_session: AsyncSession,
    prefix_filler_count: int,
    suffix_filler_count: int,
    combined_word_count: int,
) -> None:
    agency = AgencyModel(
        id=uuid.uuid4(),
        name="Long Forward Agency",
        email="long-forward-agency@example.test",
    )
    other_agency = AgencyModel(
        id=uuid.uuid4(),
        name="Other Long Forward Agency",
        email="other-long-forward-agency@example.test",
    )
    owner = _user(
        email="long-forward-owner@example.test",
        agency_id=agency.id,
    )
    same_agency_user = _user(
        email="long-forward-other-user@example.test",
        agency_id=agency.id,
    )
    other_agency_user = _user(
        email="long-forward-other-agency@example.test",
        agency_id=other_agency.id,
    )
    db_session.add_all([agency, other_agency, owner, same_agency_user, other_agency_user])
    await db_session.flush()
    visible_group = _group(
        agency_id=agency.id,
        name="Bluechip - Vietnam July 2026",
        creator_id=owner.id,
    )
    partial_name_group = _group(
        agency_id=agency.id,
        name="Chip Vietnam July 2026",
        creator_id=owner.id,
    )
    unauthorized_group = _group(
        agency_id=agency.id,
        name="Bluechip / Vietnam July 2026",
        creator_id=same_agency_user.id,
    )
    other_agency_group = _group(
        agency_id=other_agency.id,
        name="Bluechip Vietnam July 2026",
        creator_id=other_agency_user.id,
    )
    db_session.add_all(
        [
            visible_group,
            partial_name_group,
            unauthorized_group,
            other_agency_group,
        ]
    )
    await db_session.flush()
    passenger = _passenger(
        group=visible_group,
        name="Name Only Hidden Passenger",
        status="confirmed",
    )
    db_session.add(passenger)
    connection = _connection(
        agency_id=agency.id,
        owner_id=owner.id,
        account="long-forward-owner@example.test",
    )
    db_session.add(connection)
    await db_session.flush()
    prefix_words = [f"prefixword{index}" for index in range(prefix_filler_count)]
    suffix_words = [f"suffixword{index}" for index in range(suffix_filler_count)]
    message = _message(
        connection=connection,
        provider_message_id="long-forwarded-message",
        subject="Fwd",
        body_excerpt=(
            f"{' '.join(prefix_words)} BLUECHIP/VIETNAM\tJULY\n2026 "
            f"{' '.join(suffix_words)}"
        ),
        group_id=None,
    )
    assert (
        len(
            re.findall(
                r"[a-z0-9]+",
                f"{message.subject} {message.body_excerpt}".casefold(),
            )
        )
        == combined_word_count
    )
    db_session.add(message)
    await db_session.flush()

    context = await _load(
        db_session,
        message=message,
        agency_id=agency.id,
        owner_user_id=owner.id,
    )

    assert context is not None
    assert list(context.aliases.values()) == [("group", visible_group.id)]
    assert [candidate.entity_type for candidate in context.request.visible_candidates] == [
        CandidateEntityType.GROUP
    ]
    assert context.request.visible_candidates[0].safe_facts[0] == (
        "name: Bluechip - Vietnam July 2026"
    )
    assert all(alias_type != "passenger" for alias_type, _entity_id in context.aliases.values())


@pytest.mark.asyncio
async def test_normalized_name_retrieval_respects_candidate_cap(
    db_session: AsyncSession,
) -> None:
    agency = AgencyModel(
        id=uuid.uuid4(),
        name="Bounded Retrieval Agency",
        email="bounded-retrieval-agency@example.test",
    )
    owner = _user(
        email="bounded-retrieval-owner@example.test",
        agency_id=agency.id,
    )
    db_session.add_all([agency, owner])
    await db_session.flush()
    groups = [
        _group(
            agency_id=agency.id,
            name=f"Bounded Journey Number {index:02d}",
            creator_id=owner.id,
        )
        for index in range(15)
    ]
    db_session.add_all(groups)
    connection = _connection(
        agency_id=agency.id,
        owner_id=owner.id,
        account="bounded-retrieval-owner@example.test",
    )
    db_session.add(connection)
    await db_session.flush()
    message = _message(
        connection=connection,
        provider_message_id="bounded-name-retrieval-message",
        subject="Forwarded group list",
        body_excerpt="; ".join(group.name for group in groups),
        group_id=None,
    )
    db_session.add(message)
    await db_session.flush()

    context = await _load(
        db_session,
        message=message,
        agency_id=agency.id,
        owner_user_id=owner.id,
        max_candidates=5,
    )

    assert context is not None
    assert len(context.request.visible_candidates) == 5
    assert len(context.aliases) == 5
    assert all(
        candidate.entity_type == CandidateEntityType.GROUP
        for candidate in context.request.visible_candidates
    )


@pytest.mark.asyncio
async def test_large_roster_prioritizes_all_duplicate_named_passengers(
    db_session: AsyncSession,
) -> None:
    agency = AgencyModel(
        id=uuid.uuid4(),
        name="Large Roster Agency",
        email="large-roster-agency@example.test",
    )
    owner = _user(
        email="large-roster-owner@example.test",
        agency_id=agency.id,
    )
    db_session.add_all([agency, owner])
    await db_session.flush()
    group = _group(
        agency_id=agency.id,
        name="Large Roster Journey",
        creator_id=owner.id,
    )
    db_session.add(group)
    await db_session.flush()
    duplicate_matches = [
        _passenger(
            group=group,
            name="Alex Kim",
            status="confirmed",
        )
        for _ in range(2)
    ]
    for index, passenger in enumerate(duplicate_matches):
        passenger.updated_at = NOW - timedelta(days=10 + index)
    decoys = [
        _passenger(
            group=group,
            name=f"Recent Decoy Passenger {index:02d}",
            status="confirmed",
        )
        for index in range(35)
    ]
    for index, passenger in enumerate(decoys):
        passenger.updated_at = NOW + timedelta(seconds=index)
    db_session.add_all([*duplicate_matches, *decoys])
    connection = _connection(
        agency_id=agency.id,
        owner_id=owner.id,
        account="large-roster-owner@example.test",
    )
    db_session.add(connection)
    await db_session.flush()
    message = _message(
        connection=connection,
        provider_message_id="large-roster-named-passenger",
        subject="Ticket revision for Alex Kim",
        body_excerpt=(
            "Please update the arrival details for Alex Kim in this group."
        ),
        group_id=group.id,
    )
    db_session.add(message)
    await db_session.flush()

    context = await _load(
        db_session,
        message=message,
        agency_id=agency.id,
        owner_user_id=owner.id,
        max_candidates=8,
    )

    assert context is not None
    passenger_ids = {
        entity_id
        for entity_type, entity_id in context.aliases.values()
        if entity_type == "passenger"
    }
    assert {item.id for item in duplicate_matches}.issubset(passenger_ids)
    matching_candidates = [
        candidate
        for candidate in context.request.visible_candidates
        if "name: Alex Kim" in candidate.safe_facts
    ]
    assert len(matching_candidates) == 2
    assert len(context.request.visible_candidates) == 8


@pytest.mark.asyncio
async def test_passenger_name_ranking_treats_punctuation_as_literal_text(
    db_session: AsyncSession,
) -> None:
    agency = AgencyModel(
        id=uuid.uuid4(),
        name="Literal Passenger Match Agency",
        email="literal-passenger-match@example.test",
    )
    owner = _user(
        email="literal-passenger-owner@example.test",
        agency_id=agency.id,
    )
    db_session.add_all([agency, owner])
    await db_session.flush()
    group = _group(
        agency_id=agency.id,
        name="Literal Passenger Match Journey",
        creator_id=owner.id,
    )
    db_session.add(group)
    await db_session.flush()
    exact_passenger = _passenger(
        group=group,
        name="Anne%Marie O'Neil",
        status="confirmed",
    )
    exact_passenger.updated_at = NOW - timedelta(days=30)
    wildcard_decoy = _passenger(
        group=group,
        name="%",
        status="confirmed",
    )
    wildcard_decoy.updated_at = NOW + timedelta(days=1)
    recent_decoy = _passenger(
        group=group,
        name="Recent Unrelated Passenger",
        status="confirmed",
    )
    recent_decoy.updated_at = NOW
    db_session.add_all(
        [exact_passenger, wildcard_decoy, recent_decoy]
    )
    connection = _connection(
        agency_id=agency.id,
        owner_id=owner.id,
        account="literal-passenger-owner@example.test",
    )
    db_session.add(connection)
    await db_session.flush()
    message = _message(
        connection=connection,
        provider_message_id="literal-passenger-name-message",
        subject="Ticket update for Anne Marie O Neil",
        body_excerpt="Please verify the revised passenger details.",
        group_id=group.id,
    )
    db_session.add(message)
    await db_session.flush()

    context = await _load(
        db_session,
        message=message,
        agency_id=agency.id,
        owner_user_id=owner.id,
        max_candidates=2,
    )

    assert context is not None
    assert list(context.aliases.values()) == [
        ("group", group.id),
        ("passenger", exact_passenger.id),
    ]


@pytest.mark.asyncio
async def test_bounded_fuzzy_and_abbreviation_group_retrieval_is_authorized(
    db_session: AsyncSession,
) -> None:
    agency = AgencyModel(
        id=uuid.uuid4(),
        name="Fuzzy Match Agency",
        email="fuzzy-match-agency@example.test",
    )
    owner = _user(
        email="fuzzy-match-owner@example.test",
        agency_id=agency.id,
    )
    other_user = _user(
        email="fuzzy-match-other@example.test",
        agency_id=agency.id,
    )
    db_session.add_all([agency, owner, other_user])
    await db_session.flush()
    visible_group = _group(
        agency_id=agency.id,
        name="Bluechip Vietnam July 2026",
        creator_id=owner.id,
    )
    hidden_duplicate = _group(
        agency_id=agency.id,
        name="Bluechip Vietnam July 2026",
        creator_id=other_user.id,
    )
    unrelated_group = _group(
        agency_id=agency.id,
        name="Sapphire Europe September 2026",
        creator_id=owner.id,
    )
    db_session.add_all(
        [visible_group, hidden_duplicate, unrelated_group]
    )
    connection = _connection(
        agency_id=agency.id,
        owner_id=owner.id,
        account="fuzzy-match-owner@example.test",
    )
    db_session.add(connection)
    await db_session.flush()

    messages = [
        _message(
            connection=connection,
            provider_message_id="misspelled-group-name",
            subject="Buechip Vietnm July 2026 arrival update",
            body_excerpt="Please review the revised itinerary.",
            group_id=None,
        ),
        _message(
            connection=connection,
            provider_message_id="abbreviated-group-name",
            subject="BVJ2026 rooming update",
            body_excerpt="The supplier changed two rooms.",
            group_id=None,
        ),
        _message(
            connection=connection,
            provider_message_id="spaced-abbreviated-group-name",
            subject="BC VN Jul 26 rooming update",
            body_excerpt="The supplier changed two rooms.",
            group_id=None,
        ),
    ]
    db_session.add_all(messages)
    await db_session.flush()

    for message in messages:
        context = await _load(
            db_session,
            message=message,
            agency_id=agency.id,
            owner_user_id=owner.id,
        )
        assert context is not None
        assert ("group", visible_group.id) in context.aliases.values()
        assert ("group", hidden_duplicate.id) not in context.aliases.values()
        assert ("group", unrelated_group.id) not in context.aliases.values()


@pytest.mark.asyncio
async def test_missing_inactive_and_wrong_agency_owners_return_none(
    db_session: AsyncSession,
) -> None:
    agency = AgencyModel(
        id=uuid.uuid4(),
        name="Owner Boundary Agency",
        email="owner-boundary-agency@example.test",
    )
    other_agency = AgencyModel(
        id=uuid.uuid4(),
        name="Wrong Owner Agency",
        email="wrong-owner-agency@example.test",
    )
    inactive_owner = _user(
        email="inactive-context-owner@example.test",
        agency_id=agency.id,
        is_active=False,
    )
    wrong_agency_owner = _user(
        email="wrong-agency-context-owner@example.test",
        agency_id=other_agency.id,
    )
    db_session.add_all([agency, other_agency, inactive_owner, wrong_agency_owner])
    await db_session.flush()
    message = EmailMessageModel(
        id=uuid.uuid4(),
        agency_id=agency.id,
        owner_user_id=inactive_owner.id,
        connection_id=uuid.uuid4(),
        provider_message_id="owner-boundary-message",
        received_at=NOW,
    )

    for owner_id in (
        uuid.uuid4(),
        inactive_owner.id,
        wrong_agency_owner.id,
    ):
        assert (
            await _load(
                db_session,
                message=message,
                agency_id=agency.id,
                owner_user_id=owner_id,
            )
            is None
        )


@pytest.mark.asyncio
async def test_message_owner_or_agency_mismatch_returns_none(
    db_session: AsyncSession,
) -> None:
    agency = AgencyModel(
        id=uuid.uuid4(),
        name="Message Envelope Agency",
        email="message-envelope-agency@example.test",
    )
    other_agency = AgencyModel(
        id=uuid.uuid4(),
        name="Other Message Envelope Agency",
        email="other-message-envelope-agency@example.test",
    )
    owner = _user(
        email="message-envelope-owner@example.test",
        agency_id=agency.id,
    )
    other_owner = _user(
        email="message-envelope-other-owner@example.test",
        agency_id=agency.id,
    )
    db_session.add_all([agency, other_agency, owner, other_owner])
    await db_session.flush()
    wrong_owner_message = EmailMessageModel(
        id=uuid.uuid4(),
        agency_id=agency.id,
        owner_user_id=other_owner.id,
        connection_id=uuid.uuid4(),
        provider_message_id="wrong-message-owner",
        subject="Another mailbox owner's private subject",
        body_excerpt="Another mailbox owner's private body.",
        received_at=NOW,
    )
    wrong_agency_message = EmailMessageModel(
        id=uuid.uuid4(),
        agency_id=other_agency.id,
        owner_user_id=owner.id,
        connection_id=uuid.uuid4(),
        provider_message_id="wrong-message-agency",
        subject="Another agency's private subject",
        body_excerpt="Another agency's private body.",
        received_at=NOW,
    )

    for message in (wrong_owner_message, wrong_agency_message):
        assert (
            await _load(
                db_session,
                message=message,
                agency_id=agency.id,
                owner_user_id=owner.id,
            )
            is None
        )


@pytest.mark.asyncio
async def test_detached_non_super_admin_owner_returns_none(
    db_session: AsyncSession,
) -> None:
    agency = AgencyModel(
        id=uuid.uuid4(),
        name="Detached Owner Target Agency",
        email="detached-owner-target@example.test",
    )
    detached_owner = _user(
        email="detached-context-owner@example.test",
        agency_id=None,
    )
    db_session.add_all([agency, detached_owner])
    await db_session.flush()
    message = EmailMessageModel(
        id=uuid.uuid4(),
        agency_id=agency.id,
        owner_user_id=detached_owner.id,
        connection_id=uuid.uuid4(),
        provider_message_id="detached-owner-message",
        received_at=NOW,
    )

    assert (
        await _load(
            db_session,
            message=message,
            agency_id=agency.id,
            owner_user_id=detached_owner.id,
        )
        is None
    )
