"""Separate roster association, private identity, and repeated-passenger policy."""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping


def selected_field_value_uniqueness(
    recipient_fields: Iterable[Mapping[str, frozenset[str]]],
    submission_fields: Iterable[Mapping[str, frozenset[str]]],
) -> tuple[frozenset[tuple[str, str]], frozenset[tuple[str, str]]]:
    """Keep private uniqueness strict while permitting one roster's party.

    An operator-selected detail may describe several travellers attached to
    one roster contact. Only roster-side collisions are ambiguous for this
    association. Name/phone alone retain the stricter existing admission rule.
    The first result remains unique on BOTH sides and is the only result that
    may authorize private identity evidence.
    """
    recipient_frequency = Counter(
        (key, value) for fields in recipient_fields
        for key, values in fields.items() for value in values
    )
    submission_frequency = Counter(
        (key, value) for fields in submission_fields
        for key, values in fields.items() for value in values
    )
    strict = frozenset(
        pair for pair, count in recipient_frequency.items()
        if count == 1 and submission_frequency[pair] == 1
    )
    roster = frozenset(
        pair for pair, count in recipient_frequency.items()
        if count == 1 and pair[0] not in {"name", "phone_number"}
    )
    return strict, roster


def duplicate_passport_submission_ids(
    identities: Iterable[tuple[uuid.UUID, frozenset[str], str | None]],
) -> tuple[uuid.UUID, ...]:
    """Return only repeated strong passport identities, never shared contacts.

    Differing known birth dates invalidate the entire passport cluster. An
    unknown birth date must not bridge two incompatible traveller identities.
    Multiple passport values on one upload are also insufficient evidence.
    """
    groups: dict[str, list[tuple[uuid.UUID, str | None]]] = defaultdict(list)
    for submission_id, passport_numbers, birth_date in identities:
        if len(passport_numbers) == 1:
            groups[next(iter(passport_numbers))].append((submission_id, birth_date))
    duplicates: set[uuid.UUID] = set()
    for identities_for_passport in groups.values():
        known_dates = {birth_date for _, birth_date in identities_for_passport if birth_date}
        ids = {submission_id for submission_id, _ in identities_for_passport}
        if len(ids) > 1 and len(known_dates) <= 1:
            duplicates.update(ids)
    return tuple(sorted(duplicates, key=str))
