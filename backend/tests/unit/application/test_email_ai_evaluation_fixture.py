from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx

from app.core.config.settings import Settings
from app.domain.value_objects.email_ai_analysis import (
    ActionDisposition,
    DeadlineResolutionStatus,
    EmailAnalysisProviderStatus,
    EmailAnalysisRequest,
    EmailRelevance,
    ReplySendState,
    VisibleEmailCandidate,
)
from app.infrastructure.ai.gemini_email_analysis_service import (
    GeminiEmailAnalysisService,
)
from app.infrastructure.email import ai_runtime
from scripts.evaluate_email_ai_live import (
    _case_failures,
    _is_critical_safety_case,
)

_FIXTURE = Path(__file__).parents[2] / "fixtures" / "email_ai_evaluation.jsonl"
_SETTINGS = Settings(app_secret_key="fixture-test", _env_file=None)


def _load_cases() -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in _FIXTURE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _provider_response(result: dict[str, Any]) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": json.dumps(
                                    result,
                                    ensure_ascii=False,
                                    separators=(",", ":"),
                                )
                            }
                        ]
                    }
                }
            ]
        },
    )


def _request(case: dict[str, Any]) -> EmailAnalysisRequest:
    return EmailAnalysisRequest(
        subject=case["subject"],
        body_text=case["body"],
        attachment_filenames=case.get("attachments", []),
        received_at=datetime.fromisoformat(case["received_at"].replace("Z", "+00:00")),
        timezone=case["timezone"],
        visible_candidates=[
            VisibleEmailCandidate(
                alias=candidate["alias"],
                entity_type=candidate["kind"],
                safe_facts=_candidate_safe_facts(candidate),
            )
            for candidate in case["candidates"]
        ],
    )


def _candidate_safe_facts(candidate: dict[str, Any]) -> list[str]:
    facts = [f"name: {candidate['label']}"]
    group_alias = candidate.get("group_alias")
    if candidate.get("kind") == "passenger" and isinstance(group_alias, str):
        facts.append(f"group alias: {group_alias}")
    return facts


def _canonical_aliases(
    case: dict[str, Any],
    result: Any,
) -> tuple[str | None, set[str]]:
    request = _request(case)
    alias_ids = {
        candidate["alias"]: uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"email-ai-evaluation:{case['case_id']}:{candidate['alias']}",
        )
        for candidate in case["candidates"]
    }
    context = SimpleNamespace(
        aliases={
            candidate["alias"]: (candidate["kind"], alias_ids[candidate["alias"]])
            for candidate in case["candidates"]
        },
        request=request,
    )
    group_id, passenger_ids = ai_runtime._canonical_link_ids(
        context=context,
        result=result,
        confidence_threshold=_SETTINGS.email_ai_auto_confidence_threshold,
    )
    inverse = {value: alias for alias, value in alias_ids.items()}
    return (
        inverse.get(group_id) if group_id is not None else None,
        {
            inverse[uuid.UUID(passenger_id)]
            for passenger_id in passenger_ids
            if uuid.UUID(passenger_id) in inverse
        },
    )


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def test_fixture_is_complete_and_has_independent_expected_and_provider_records() -> None:
    cases = _load_cases()

    assert len(cases) >= 22
    assert len({case["case_id"] for case in cases}) == len(cases)
    assert all(case.get("expected") for case in cases)
    assert all(case.get("provider_output") for case in cases)
    assert any("must_not_contain" in case["expected"] for case in cases)
    assert any(case["expected"].get("draft_must_be_unsent") for case in cases)
    assert any(case["case_id"] == "bilingual_request" for case in cases)
    assert any(case["case_id"] == "ambiguous_multiple_groups" for case in cases)
    required_difficult_cases = {
        "missing_subject",
        "replacement_traveller",
        "revised_attachment",
        "several_passengers",
        "unclear_filename",
        "conflicting_deadlines",
        "forwarded_thread",
        "misspelled_names",
        "abbreviated_client_group",
    }
    assert required_difficult_cases.issubset(
        {case["case_id"] for case in cases}
    )
    assert {
        "instruction_injection",
        "high_risk_cancellation",
        "safe_draft",
    }.issubset(
        {
            case["case_id"]
            for case in cases
            if _is_critical_safety_case(case)
        }
    )


async def test_synthetic_evaluation_runs_through_gemini_contract_and_policy() -> None:
    cases = _load_cases()

    for case in cases:
        captured_payloads: list[dict[str, Any]] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            captured_payloads.append(json.loads(request.content))
            return _provider_response(case["provider_output"])

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await GeminiEmailAnalysisService(
                api_key="fixture-only-key",
                model="fixture-evaluation-model",
                timeout_seconds=4.0,
                review_confidence_threshold=(
                    _SETTINGS.email_ai_auto_confidence_threshold
                ),
                deadline_confidence_threshold=(
                    _SETTINGS.email_ai_deadline_confidence_threshold
                ),
                http_client=client,
                repair_invalid_response=False,
            ).analyze(_request(case))

        expected = case["expected"]
        assert result.provider_status == EmailAnalysisProviderStatus.ANALYZED, case["case_id"]
        assert len(captured_payloads) == 1, case["case_id"]
        request_schema = captured_payloads[0]["generationConfig"]["responseSchema"]
        assert request_schema["type"] == "OBJECT", case["case_id"]
        assert "tools" not in captured_payloads[0], case["case_id"]

        expected_relevance = (
            result.relevance != EmailRelevance.UNRELATED
        )
        assert expected_relevance is expected["relevant"], case["case_id"]

        if "intent" in expected:
            assert result.intent.value == expected["intent"], case["case_id"]
        if "priority" in expected:
            assert result.priority.value == expected["priority"], case["case_id"]
        if "needs_attention" in expected:
            assert result.needs_review is expected["needs_attention"], case["case_id"]

        if "linked_aliases" in expected:
            assert {link.alias for link in result.candidate_links} == set(
                expected["linked_aliases"]
            ), case["case_id"]
        if (
            "canonical_group_alias" in expected
            or "canonical_passenger_aliases" in expected
        ):
            group_alias, passenger_aliases = _canonical_aliases(case, result)
            assert group_alias == expected.get("canonical_group_alias"), case[
                "case_id"
            ]
            assert passenger_aliases == set(
                expected.get("canonical_passenger_aliases", [])
            ), case["case_id"]

        visible_aliases = {
            candidate["alias"] for candidate in case["candidates"]
        }
        assert {
            link.alias for link in result.candidate_links
        }.issubset(visible_aliases), case["case_id"]
        for forbidden_alias in expected.get("forbidden_aliases", []):
            assert forbidden_alias not in visible_aliases, case["case_id"]
            assert all(
                link.alias != forbidden_alias for link in result.candidate_links
            ), case["case_id"]
            assert all(
                decision.target_alias != forbidden_alias
                for decision in result.action_decisions
            ), case["case_id"]

        if "deadline_utc" in expected or "deadline_local_date" in expected:
            assert len(result.deadlines) == 1, case["case_id"]
            deadline = result.deadlines[0]
            assert deadline.status == DeadlineResolutionStatus.RESOLVED, case["case_id"]
            assert deadline.due_at is not None, case["case_id"]
            if "deadline_utc" in expected:
                assert _utc_text(deadline.due_at) == expected["deadline_utc"], case[
                    "case_id"
                ]
            if "deadline_local_date" in expected:
                assert (
                    deadline.due_at.date().isoformat()
                    == expected["deadline_local_date"]
                ), case["case_id"]

        if "ambiguous_deadline" in expected:
            assert result.deadlines, case["case_id"]
            expected_status = (
                DeadlineResolutionStatus.REVIEW_REQUIRED
                if expected["ambiguous_deadline"]
                else DeadlineResolutionStatus.RESOLVED
            )
            assert result.deadlines[0].status == expected_status, case["case_id"]
        if "deadline_count" in expected:
            assert len(result.deadlines) == expected["deadline_count"], case[
                "case_id"
            ]

        proposal_types = {proposal.action.value for proposal in result.proposals}
        if "proposal_types" in expected:
            assert proposal_types == set(expected["proposal_types"]), case["case_id"]
            proposal_decisions = {
                decision.action: decision.disposition
                for decision in result.action_decisions
            }
            for action in expected["proposal_types"]:
                assert (
                    proposal_decisions[action] == ActionDisposition.PROPOSAL_ONLY
                ), case["case_id"]

        blocked_actions = {
            decision.action
            for decision in result.action_decisions
            if decision.disposition == ActionDisposition.BLOCKED
        }
        if "blocked_action_types" in expected:
            assert blocked_actions == set(expected["blocked_action_types"]), case["case_id"]

        if expected.get("draft_must_be_unsent"):
            assert result.reply_draft is not None, case["case_id"]
            assert result.reply_draft.send_state == ReplySendState.UNSENT, case["case_id"]
            assert "send_email" not in proposal_types, case["case_id"]

        serialized_result = json.dumps(
            result.model_dump(mode="json"),
            ensure_ascii=False,
        ).casefold()
        for forbidden_text in expected.get("must_not_contain", []):
            assert forbidden_text.casefold() not in serialized_result, case["case_id"]

        live_failures = _case_failures(
            case=case,
            result=result,
            link_confidence_threshold=(
                _SETTINGS.email_ai_auto_confidence_threshold
            ),
        )
        assert live_failures == [], case["case_id"]
        provider_failure = result.model_copy(
            update={
                "provider_status": (
                    EmailAnalysisProviderStatus.PROVIDER_UNAVAILABLE
                )
            }
        )
        assert "provider_status" in _case_failures(
            case=case,
            result=provider_failure,
            link_confidence_threshold=(
                _SETTINGS.email_ai_auto_confidence_threshold
            ),
        ), case["case_id"]
