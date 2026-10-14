"""The additive lookup can resume and never changes authoritative passport data."""

import pytest

from app.application.travellers.passport_lookup_index import backfill_passport_lookup
from tests.integration.traveller_reuse_fixtures import reuse_context, seed_person


@pytest.mark.asyncio
async def test_number_lookup_backfill_is_bounded_resumable_and_preserves_history(db_session, test_settings):
    service, _, group = await reuse_context(db_session, test_settings)
    people = [await seed_person(service, group, index) for index in range(1, 4)]
    authoritative = [(person.passport.number_fingerprint, person.passport.number_ciphertext,
        person.passport.issuing_country, person.passport.document_type, person.passport.status,
        person.document.fields_ciphertext, person.document.revision_number) for person in people]
    assert await backfill_passport_lookup(db_session, service.crypto, batch_size=1) == 1
    await db_session.commit()
    assert sum(person.passport.number_lookup_fingerprint is not None for person in people) == 1
    assert await backfill_passport_lookup(db_session, service.crypto, batch_size=1) == 1
    await db_session.commit()
    assert await backfill_passport_lookup(db_session, service.crypto, batch_size=1) == 1
    await db_session.commit()
    assert await backfill_passport_lookup(db_session, service.crypto, batch_size=1) == 0
    for person, before in zip(people, authoritative, strict=True):
        assert person.passport.number_lookup_fingerprint == service.crypto.scoped_digest(
            "passport-number", group.agency_id, group.company_id, person.number)
        assert before == (person.passport.number_fingerprint, person.passport.number_ciphertext,
            person.passport.issuing_country, person.passport.document_type, person.passport.status,
            person.document.fields_ciphertext, person.document.revision_number)


@pytest.mark.asyncio
async def test_number_lookup_backfill_does_not_touch_other_key_versions_or_existing_values(db_session, test_settings):
    service, _, group = await reuse_context(db_session, test_settings)
    first, second, third = [await seed_person(service, group, index) for index in range(1, 4)]
    first.passport.fingerprint_key_version = "retired-key"
    second.passport.number_lookup_fingerprint = "a" * 64
    await db_session.commit()
    assert await backfill_passport_lookup(db_session, service.crypto, batch_size=0) == 1
    assert first.passport.number_lookup_fingerprint is None
    assert second.passport.number_lookup_fingerprint == "a" * 64
    assert third.passport.number_lookup_fingerprint
    assert await backfill_passport_lookup(db_session, service.crypto, batch_size=10_000) == 0
