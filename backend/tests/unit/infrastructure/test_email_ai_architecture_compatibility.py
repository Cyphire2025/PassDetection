"""Leased task values retain their legacy serialization and public imports."""

import dataclasses
import pickle
import uuid
from typing import get_type_hints

from app.application.use_cases.email_integrations.analysis_contract import EMAIL_AI_SCHEMA_VERSION
from app.infrastructure.email import ai_claim, ai_runtime


def test_claim_task_boundary_preserves_single_class_identity_and_original_module():
    claim = ai_runtime.EmailAiClaim(
        analysis_id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        owner_user_id=uuid.uuid4(),
        connection_id=uuid.uuid4(),
        message_id=uuid.uuid4(),
        provider_account_id="synthetic-provider",
        sync_generation=3,
        lease_token="synthetic-lease-token",
    )
    assert type(claim) is ai_claim.EmailAiClaim
    assert type(claim).__module__ == ai_runtime.__name__
    assert pickle.loads(pickle.dumps(claim)) == claim
    assert list(get_type_hints(type(claim))) == [field.name for field in dataclasses.fields(claim)]
    assert claim.task_kwargs() == {
        "analysis_id": str(claim.analysis_id),
        "agency_id": str(claim.agency_id),
        "owner_user_id": str(claim.owner_user_id),
        "connection_id": str(claim.connection_id),
        "message_id": str(claim.message_id),
        "provider_account_id": "synthetic-provider",
        "sync_generation": 3,
        "lease_token": "synthetic-lease-token",
    }
    assert ai_runtime.EMAIL_AI_SCHEMA_VERSION == EMAIL_AI_SCHEMA_VERSION
    assert type(claim).__dataclass_params__.frozen
