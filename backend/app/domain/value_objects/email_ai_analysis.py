"""Strict value objects for bounded AI-assisted email analysis.

These models deliberately contain no database identifiers. The AI provider sees
only opaque candidate aliases supplied by the caller, and every provider field
is bounded before it can enter the application.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

CandidateAlias = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=32,
        pattern=r"^[a-z][a-z0-9_-]*$",
    ),
]
ShortText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=160),
]
ExplanationText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=320),
]
Confidence = Annotated[float, Field(ge=0.0, le=1.0)]
EmailDomain = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=253,
        pattern=r"^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$",
    ),
]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EmailRelevance(str, Enum):
    RELEVANT = "relevant"
    POSSIBLY_RELEVANT = "possibly_relevant"
    UNRELATED = "unrelated"


class EmailIntent(str, Enum):
    DOCUMENT_SUBMISSION = "document_submission"
    DOCUMENT_REQUEST = "document_request"
    ITINERARY_UPDATE = "itinerary_update"
    ITINERARY_CHANGE = "itinerary_change"
    VISA_STATUS = "visa_status"
    INFORMATION_REQUEST = "information_request"
    ACTION_REQUEST = "action_request"
    DEADLINE_NOTICE = "deadline_notice"
    DEADLINE_UPDATE = "deadline_update"
    CANCELLATION = "cancellation"
    PAYMENT = "payment"
    GENERAL_TRAVEL = "general_travel"
    OTHER = "other"


class EmailPriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class CandidateEntityType(str, Enum):
    GROUP = "group"
    PASSENGER = "passenger"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class EmailRiskCode(str, Enum):
    PROMPT_INJECTION = "prompt_injection"
    CREDENTIAL_REQUEST = "credential_request"
    EXTERNAL_LINK = "external_link"
    IDENTITY_CHANGE = "identity_change"
    FINANCIAL = "financial"
    CANCELLATION = "cancellation"
    BULK_OR_SENSITIVE_DATA = "bulk_or_sensitive_data"
    OTHER = "other"


class EmailActionType(str, Enum):
    LINK_ENTITY = "link_entity"
    CREATE_REMINDER = "create_reminder"
    PREPARE_REPLY_DRAFT = "prepare_reply_draft"
    SEND_EMAIL = "send_email"
    SEND_WHATSAPP = "send_whatsapp"
    MODIFY_PASSENGER = "modify_passenger"
    REPLACE_PASSENGER = "replace_passenger"
    CANCEL_BOOKING = "cancel_booking"
    TAKE_PAYMENT = "take_payment"
    DELETE_RECORD = "delete_record"
    EXPORT_DATA = "export_data"
    FETCH_EXTERNAL_URL = "fetch_external_url"


class ReplyTone(str, Enum):
    PROFESSIONAL = "professional"
    CONCISE = "concise"
    WARM = "warm"


class ReplySendState(str, Enum):
    UNSENT = "unsent"


class DeadlineResolutionStatus(str, Enum):
    RESOLVED = "resolved"
    REVIEW_REQUIRED = "review_required"


class ActionDisposition(str, Enum):
    PROPOSAL_ONLY = "proposal_only"
    BLOCKED = "blocked"


class EmailAnalysisProviderStatus(str, Enum):
    ANALYZED = "analyzed"
    NOT_CONFIGURED = "not_configured"
    PROVIDER_REJECTED = "provider_rejected"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    TIMEOUT = "timeout"
    INVALID_RESPONSE = "invalid_response"


class VisibleEmailCandidate(_StrictModel):
    """Minimal server-authorized context visible to the model."""

    alias: CandidateAlias
    entity_type: CandidateEntityType
    safe_facts: list[ShortText] = Field(default_factory=list, max_length=8)


class EmailAnalysisRequest(_StrictModel):
    """Provider-independent, bounded input for one email analysis."""

    subject: str = Field(default="", max_length=500)
    body_text: str = Field(default="", max_length=16_000)
    attachment_filenames: list[Annotated[str, Field(max_length=180)]] = Field(
        default_factory=list,
        max_length=20,
    )
    sender_display_name: Annotated[str, Field(max_length=160)] | None = None
    sender_domain: EmailDomain | None = None
    recipient_domains: list[EmailDomain] = Field(default_factory=list, max_length=20)
    connected_account_domain: EmailDomain | None = None
    received_at: datetime
    timezone: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=64),
    ]
    visible_candidates: list[VisibleEmailCandidate] = Field(default_factory=list, max_length=24)

    @field_validator("received_at")
    @classmethod
    def require_aware_received_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("received_at must include a UTC offset")
        return value

    @field_validator("visible_candidates")
    @classmethod
    def require_unique_aliases(
        cls,
        value: list[VisibleEmailCandidate],
    ) -> list[VisibleEmailCandidate]:
        aliases = [candidate.alias for candidate in value]
        if len(aliases) != len(set(aliases)):
            raise ValueError("visible candidate aliases must be unique")
        return value


class CandidateLink(_StrictModel):
    alias: CandidateAlias
    confidence: Confidence
    rationale: ExplanationText


class DeadlineCandidate(_StrictModel):
    source_text: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=240),
    ]
    expression: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=120),
    ]
    confidence: Confidence


class EmailRisk(_StrictModel):
    code: EmailRiskCode
    level: RiskLevel
    rationale: ExplanationText


class EmailActionProposal(_StrictModel):
    action: EmailActionType
    target_alias: CandidateAlias | None = None
    deadline_expression: (
        Annotated[
            str,
            StringConstraints(strip_whitespace=True, min_length=1, max_length=120),
        ]
        | None
    ) = None
    rationale: ExplanationText
    confidence: Confidence


class UnsentReplyDraft(_StrictModel):
    subject: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
    ]
    body: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=2_000),
    ]
    tone: ReplyTone
    send_state: ReplySendState = ReplySendState.UNSENT


class GeminiEmailAnalysisPayload(_StrictModel):
    """Exact JSON object accepted from the Gemini transport."""

    relevance: EmailRelevance
    intent: EmailIntent
    priority: EmailPriority
    confidence: Confidence
    summary: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=600),
    ]
    candidate_links: list[CandidateLink] = Field(default_factory=list, max_length=8)
    deadlines: list[DeadlineCandidate] = Field(default_factory=list, max_length=8)
    risks: list[EmailRisk] = Field(default_factory=list, max_length=8)
    missing_information: list[ShortText] = Field(default_factory=list, max_length=12)
    proposals: list[EmailActionProposal] = Field(default_factory=list, max_length=8)
    reply_draft: UnsentReplyDraft | None = None

    @field_validator("candidate_links")
    @classmethod
    def require_unique_candidate_links(
        cls,
        value: list[CandidateLink],
    ) -> list[CandidateLink]:
        aliases = [link.alias for link in value]
        if len(aliases) != len(set(aliases)):
            raise ValueError("candidate links must not repeat an alias")
        return value


class ResolvedDeadline(_StrictModel):
    source_text: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=240),
    ]
    expression: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=120),
    ]
    confidence: Confidence
    status: DeadlineResolutionStatus
    due_at: datetime | None = None
    reason_code: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=64),
    ]

    @field_validator("due_at")
    @classmethod
    def require_aware_due_at(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("due_at must include a UTC offset")
        return value


class ActionPolicyDecision(_StrictModel):
    action: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=64),
    ]
    disposition: ActionDisposition
    risk_level: RiskLevel
    reason_code: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=64),
    ]
    target_alias: CandidateAlias | None = None


class EmailAnalysisResult(_StrictModel):
    provider_status: EmailAnalysisProviderStatus
    reason_code: (
        Annotated[
            str,
            StringConstraints(strip_whitespace=True, min_length=1, max_length=64),
        ]
        | None
    ) = None
    model: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=128),
    ]
    repair_attempted: bool = False
    relevance: EmailRelevance
    intent: EmailIntent
    priority: EmailPriority
    confidence: Confidence
    summary: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=600),
    ]
    candidate_links: list[CandidateLink] = Field(default_factory=list, max_length=8)
    deadlines: list[ResolvedDeadline] = Field(default_factory=list, max_length=8)
    risks: list[EmailRisk] = Field(default_factory=list, max_length=8)
    missing_information: list[ShortText] = Field(default_factory=list, max_length=12)
    proposals: list[EmailActionProposal] = Field(default_factory=list, max_length=8)
    action_decisions: list[ActionPolicyDecision] = Field(default_factory=list, max_length=8)
    reply_draft: UnsentReplyDraft | None = None
    needs_review: bool

    @classmethod
    def review_fallback(
        cls,
        *,
        provider_status: EmailAnalysisProviderStatus,
        reason_code: str,
        model: str,
        repair_attempted: bool = False,
    ) -> Self:
        return cls(
            provider_status=provider_status,
            reason_code=reason_code,
            model=model,
            repair_attempted=repair_attempted,
            relevance=EmailRelevance.POSSIBLY_RELEVANT,
            intent=EmailIntent.OTHER,
            priority=EmailPriority.NORMAL,
            confidence=0.0,
            summary="Automated email analysis was unavailable; manual review is required.",
            candidate_links=[],
            deadlines=[],
            risks=[],
            missing_information=[],
            proposals=[],
            action_decisions=[],
            reply_draft=None,
            needs_review=True,
        )
