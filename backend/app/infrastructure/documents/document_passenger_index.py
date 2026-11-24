"""Focused passenger index policy; no parser or I/O side effects."""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any

from app.domain.entities.entities import PassportSubmission
from app.infrastructure.documents.document_identity_aliases import DocumentIdentityAliases
from app.infrastructure.documents.document_matcher_models import (
    DocumentMatchIndex,
    PassengerIdentifier,
    _IdentifierOwner,
    _PassengerProfile,
)
from app.infrastructure.documents.document_matcher_rules import (
    _NAME_NOISE_TOKENS,
    _PASSPORT_KEYS,
)


class DocumentPassengerIndex(DocumentIdentityAliases):
    def build_index(
        self,
        passengers: list[PassportSubmission],
        *,
        agency_id: uuid.UUID | None = None,
        group_id: uuid.UUID | None = None,
        supplemental_identifiers: Iterable[PassengerIdentifier] = (),
    ) -> DocumentMatchIndex:
        """Build bounded lookup tables once for a verify/upload request."""
        limits = self._identity_limits()

        scoped_passengers = {
            passenger.id: passenger
            for passenger in passengers
            if (agency_id is None or passenger.agency_id == agency_id)
            and (group_id is None or passenger.group_id == group_id)
        }
        passport_owners: dict[str, set[uuid.UUID]] = defaultdict(set)
        name_owners: dict[tuple[str, ...], set[uuid.UUID]] = defaultdict(set)
        compact_name_owners: dict[str, set[uuid.UUID]] = defaultdict(set)
        partial_name_pair_owners: dict[tuple[str, ...], set[uuid.UUID]] = defaultdict(set)
        identifier_owners: dict[str, set[_IdentifierOwner]] = defaultdict(set)
        name_token_owners: dict[str, set[uuid.UUID]] = defaultdict(set)
        profiles: dict[uuid.UUID, _PassengerProfile] = {}
        direct_identifier_counts: dict[uuid.UUID, int] = {}

        for passenger_id, passenger in scoped_passengers.items():
            fields = self._passport_fields(passenger)
            names = self._normalized_passenger_names(passenger, fields)
            profiles[passenger_id] = _PassengerProfile(passenger_id, names)
            for name in names:
                name_owners[name].add(passenger_id)
                for alias in self._compact_name_aliases(name):
                    compact_name_owners[alias].add(passenger_id)
                for partial_alias in self._partial_name_pair_aliases(name):
                    partial_name_pair_owners[partial_alias].add(passenger_id)
                for token in set(name):
                    if token not in _NAME_NOISE_TOKENS and len(token) > 1:
                        name_token_owners[token].add(passenger_id)

            for raw_value in self._mapping_values(fields, _PASSPORT_KEYS):
                if value := self._normalize_identifier(raw_value):
                    passport_owners[value].add(passenger_id)

            direct_mappings: tuple[tuple[Mapping[str, Any], str], ...] = (
                (dict(getattr(passenger, "staff_metadata", None) or {}), "group Excel"),
                (fields, "passenger details"),
            )
            identifier_count = 0
            for mapping, source in direct_mappings:
                for value, kind in self._identifier_aliases(mapping):
                    owner = _IdentifierOwner(passenger_id, kind, source)
                    owners = identifier_owners[value]
                    if owner not in owners:
                        owners.add(owner)
                        identifier_count += 1
                    if identifier_count >= limits.passenger_identifiers:
                        break
                if identifier_count >= limits.passenger_identifiers:
                    break
            if identifier_count < limits.passenger_identifiers:
                for answer in (
                    list(getattr(passenger, "custom_answers", None) or [])
                    + list(getattr(passenger, "custom_detail_answers", None) or [])
                )[:40]:
                    if not isinstance(answer, Mapping):
                        continue
                    label = answer.get("label")
                    value = answer.get("value")
                    for alias, kind in self._identifier_aliases({str(label or ""): value}):
                        owner = _IdentifierOwner(passenger_id, kind, "group details")
                        owners = identifier_owners[alias]
                        if owner not in owners:
                            owners.add(owner)
                            identifier_count += 1
                        if identifier_count >= limits.passenger_identifiers:
                            break
                    if identifier_count >= limits.passenger_identifiers:
                        break
            direct_identifier_counts[passenger_id] = identifier_count

        supplemental_counts: dict[uuid.UUID, int] = defaultdict(int)
        supplemental_total = 0
        for input_index, supplemental in enumerate(supplemental_identifiers):
            if (
                input_index >= limits.supplemental_inputs
                or supplemental_total >= limits.supplemental_per_request
            ):
                break
            supplemental_passenger = scoped_passengers.get(supplemental.passenger_id)
            if (
                supplemental_passenger is None
                or supplemental_counts[supplemental.passenger_id]
                >= limits.supplemental_per_passenger
                or direct_identifier_counts.get(supplemental.passenger_id, 0)
                + supplemental_counts[supplemental.passenger_id]
                >= limits.passenger_identifiers
                or supplemental.agency_id != supplemental_passenger.agency_id
                or supplemental.group_id != supplemental_passenger.group_id
                or (agency_id is not None and supplemental.agency_id != agency_id)
                or (group_id is not None and supplemental.group_id != group_id)
            ):
                continue
            if value := self._normalize_identifier(supplemental.value):
                owner = _IdentifierOwner(
                    supplemental.passenger_id,
                    self._safe_identifier_kind(supplemental.kind),
                    self._safe_identifier_source(supplemental.source),
                )
                owners = identifier_owners[value]
                if owner in owners:
                    continue
                owners.add(owner)
                supplemental_counts[supplemental.passenger_id] += 1
                supplemental_total += 1

        return DocumentMatchIndex(
            passengers_by_id=scoped_passengers,
            profiles_by_id=profiles,
            passports=self._freeze_uuid_index(passport_owners),
            names=self._freeze_name_index(name_owners),
            compact_names=self._freeze_uuid_index(compact_name_owners),
            partial_name_pairs=self._freeze_name_index(partial_name_pair_owners),
            identifiers={
                value: tuple(
                    sorted(
                        owners,
                        key=lambda owner: (str(owner.passenger_id), owner.kind, owner.source),
                    )
                )
                for value, owners in identifier_owners.items()
            },
            name_token_passengers=self._freeze_uuid_index(name_token_owners),
            name_lengths=tuple(sorted({len(name) for name in name_owners}, reverse=True)),
        )

    def stored_identifier_aliases(
        self,
        mapping: Mapping[str, Any],
    ) -> tuple[tuple[str, str], ...]:
        """Expose the canonical bounded alias policy to scoped data loaders."""

        return tuple(self._identifier_aliases(mapping))
