"""Retain trip answers only while their configured meaning is unchanged."""
import json

from app.application.platform_policies import PlatformPolicies
from app.application.travellers.draft_contracts import DraftPayload
from app.application.travellers.draft_store import DraftStore
from app.application.travellers.requirements import requirement_signatures
from app.infrastructure.database.models import ClientGroupModel
from app.infrastructure.database.traveller_returning_draft_models import (
    TravellerReturningDraftModel as Draft,
)


def current_answers(service: DraftStore, previous: Draft, group: ClientGroupModel, policies: PlatformPolicies) -> dict[str, dict[str, str]]:
    payload = DraftPayload.model_validate_json(service.crypto.decrypt(previous.payload_ciphertext))
    old = json.loads(service.crypto.decrypt(previous.requirements_ciphertext)) if previous.requirements_ciphertext else {}
    current = requirement_signatures(group, policies)
    return {section: {key: value for key, value in getattr(payload, section).items()
        if current[section].get(key) is not None and current[section].get(key) == old.get(section, {}).get(key)}
        for section in current}


def refresh_answers(service: DraftStore, draft: Draft, group: ClientGroupModel, policies: PlatformPolicies) -> None:
    payload = DraftPayload.model_validate_json(service.crypto.decrypt(draft.payload_ciphertext))
    draft.payload_ciphertext = service.crypto.encrypt(payload.model_copy(update=current_answers(service, draft, group, policies)).model_dump_json())
    draft.requirements_ciphertext = service.crypto.encrypt(json.dumps(requirement_signatures(group, policies), sort_keys=True))
