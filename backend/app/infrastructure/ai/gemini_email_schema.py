"""Strict bounded Gemini email response schema with visible aliases."""

from __future__ import annotations

from typing import Any

from app.domain.value_objects.email_ai_analysis import (
    EmailActionType,
    EmailIntent,
    EmailPriority,
    EmailRelevance,
    EmailRiskCode,
    ReplySendState,
    ReplyTone,
    RiskLevel,
)


def _response_schema(*, candidate_aliases: list[str]) -> dict[str, Any]:
    alias_schema: dict[str, Any] = {"type": "STRING"}
    if candidate_aliases:
        alias_schema["enum"] = candidate_aliases
    candidate_link_schema: dict[str, Any] = {
        "type": "ARRAY",
        "minItems": 0,
        "maxItems": min(8, len(candidate_aliases)),
        "items": {
            "type": "OBJECT",
            "properties": {
                "alias": alias_schema,
                "confidence": {"type": "NUMBER", "minimum": 0, "maximum": 1},
                "rationale": {"type": "STRING", "maxLength": 320},
            },
            "required": ["alias", "confidence", "rationale"],
        },
    }
    return {
        "type": "OBJECT",
        "properties": {
            "relevance": {
                "type": "STRING",
                "enum": [value.value for value in EmailRelevance],
            },
            "intent": {
                "type": "STRING",
                "enum": [value.value for value in EmailIntent],
            },
            "priority": {
                "type": "STRING",
                "enum": [value.value for value in EmailPriority],
            },
            "confidence": {
                "type": "NUMBER",
                "minimum": 0,
                "maximum": 1,
            },
            "summary": {"type": "STRING", "maxLength": 600},
            "candidate_links": candidate_link_schema,
            "deadlines": {
                "type": "ARRAY",
                "minItems": 0,
                "maxItems": 8,
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "source_text": {"type": "STRING", "maxLength": 240},
                        "expression": {"type": "STRING", "maxLength": 120},
                        "confidence": {
                            "type": "NUMBER",
                            "minimum": 0,
                            "maximum": 1,
                        },
                    },
                    "required": ["source_text", "expression", "confidence"],
                },
            },
            "risks": {
                "type": "ARRAY",
                "minItems": 0,
                "maxItems": 8,
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "code": {
                            "type": "STRING",
                            "enum": [value.value for value in EmailRiskCode],
                        },
                        "level": {
                            "type": "STRING",
                            "enum": [value.value for value in RiskLevel],
                        },
                        "rationale": {"type": "STRING", "maxLength": 320},
                    },
                    "required": ["code", "level", "rationale"],
                },
            },
            "missing_information": {
                "type": "ARRAY",
                "minItems": 0,
                "maxItems": 12,
                "items": {"type": "STRING", "maxLength": 160},
            },
            "proposals": {
                "type": "ARRAY",
                "minItems": 0,
                "maxItems": 8,
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "action": {
                            "type": "STRING",
                            "enum": [value.value for value in EmailActionType],
                        },
                        "target_alias": alias_schema,
                        "deadline_expression": {
                            "type": "STRING",
                            "maxLength": 120,
                        },
                        "rationale": {"type": "STRING", "maxLength": 320},
                        "confidence": {
                            "type": "NUMBER",
                            "minimum": 0,
                            "maximum": 1,
                        },
                    },
                    "required": ["action", "rationale", "confidence"],
                },
            },
            "reply_draft": {
                "type": "OBJECT",
                "properties": {
                    "subject": {"type": "STRING", "maxLength": 200},
                    "body": {"type": "STRING", "maxLength": 2_000},
                    "tone": {
                        "type": "STRING",
                        "enum": [value.value for value in ReplyTone],
                    },
                    "send_state": {
                        "type": "STRING",
                        "enum": [ReplySendState.UNSENT.value],
                    },
                },
                "required": ["subject", "body", "tone", "send_state"],
            },
        },
        "required": [
            "relevance",
            "intent",
            "priority",
            "confidence",
            "summary",
            "candidate_links",
            "deadlines",
            "risks",
            "missing_information",
            "proposals",
        ],
    }
