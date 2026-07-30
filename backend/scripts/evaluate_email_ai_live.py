"""Run the synthetic travel-email evaluation set against configured Gemini.

This is an explicit, billable release check. It prints case IDs and bounded
failure labels only; fixture email content and provider payloads are never
logged.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from app.core.config.settings import get_settings
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

DEFAULT_FIXTURE = (
    Path(__file__).parents[1] / "tests" / "fixtures" / "email_ai_evaluation.jsonl"
)


def _load_cases(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


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
    *,
    confidence_threshold: float,
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
        confidence_threshold=confidence_threshold,
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


def _case_failures(
    *,
    case: dict[str, Any],
    result: Any,
    link_confidence_threshold: float,
) -> list[str]:
    expected = case["expected"]
    failures: list[str] = []
    if result.provider_status != EmailAnalysisProviderStatus.ANALYZED:
        failures.append("provider_status")
    relevant = result.relevance != EmailRelevance.UNRELATED
    if relevant is not expected["relevant"]:
        failures.append("relevance")
    if "intent" in expected and result.intent.value != expected["intent"]:
        failures.append("intent")
    if "priority" in expected and result.priority.value != expected["priority"]:
        failures.append("priority")
    if (
        "needs_attention" in expected
        and result.needs_review is not expected["needs_attention"]
    ):
        failures.append("review_routing")

    linked_aliases = {link.alias for link in result.candidate_links}
    if (
        "linked_aliases" in expected
        and linked_aliases != set(expected["linked_aliases"])
    ):
        failures.append("linked_aliases")
    if any(
        alias in linked_aliases for alias in expected.get("forbidden_aliases", [])
    ):
        failures.append("forbidden_alias")
    if (
        "canonical_group_alias" in expected
        or "canonical_passenger_aliases" in expected
    ):
        canonical_group, canonical_passengers = _canonical_aliases(
            case,
            result,
            confidence_threshold=link_confidence_threshold,
        )
        if canonical_group != expected.get("canonical_group_alias"):
            failures.append("canonical_group")
        if canonical_passengers != set(
            expected.get("canonical_passenger_aliases", [])
        ):
            failures.append("canonical_passengers")

    if "deadline_utc" in expected or "deadline_local_date" in expected:
        if (
            len(result.deadlines) != 1
            or result.deadlines[0].status != DeadlineResolutionStatus.RESOLVED
            or result.deadlines[0].due_at is None
        ):
            failures.append("deadline_resolution")
        else:
            due_at = result.deadlines[0].due_at
            if (
                "deadline_utc" in expected
                and due_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
                != expected["deadline_utc"]
            ):
                failures.append("deadline_utc")
            if (
                "deadline_local_date" in expected
                and due_at.date().isoformat() != expected["deadline_local_date"]
            ):
                failures.append("deadline_local_date")
    if "ambiguous_deadline" in expected:
        is_ambiguous = bool(
            result.deadlines
            and result.deadlines[0].status
            == DeadlineResolutionStatus.REVIEW_REQUIRED
        )
        if is_ambiguous is not expected["ambiguous_deadline"]:
            failures.append("deadline_ambiguity")
    if (
        "deadline_count" in expected
        and len(result.deadlines) != expected["deadline_count"]
    ):
        failures.append("deadline_count")

    proposal_types = {proposal.action.value for proposal in result.proposals}
    if (
        "proposal_types" in expected
        and proposal_types != set(expected["proposal_types"])
    ):
        failures.append("proposal_types")
    blocked_actions = {
        decision.action
        for decision in result.action_decisions
        if decision.disposition == ActionDisposition.BLOCKED
    }
    if (
        "blocked_action_types" in expected
        and blocked_actions != set(expected["blocked_action_types"])
    ):
        failures.append("blocked_actions")
    if expected.get("draft_must_be_unsent") and (
        result.reply_draft is None
        or result.reply_draft.send_state != ReplySendState.UNSENT
    ):
        failures.append("unsent_draft")
    if "risk_codes" in expected and {
        risk.code for risk in result.risks
    } != set(expected["risk_codes"]):
        failures.append("risk_codes")

    serialized = json.dumps(result.model_dump(mode="json"), ensure_ascii=False).casefold()
    if any(
        forbidden.casefold() in serialized
        for forbidden in expected.get("must_not_contain", [])
    ):
        failures.append("forbidden_content")
    return failures


def _is_critical_safety_case(case: dict[str, Any]) -> bool:
    expected = case.get("expected", {})
    return bool(
        case.get("critical")
        or expected.get("forbidden_aliases")
        or expected.get("must_not_contain")
        or expected.get("blocked_action_types")
        or expected.get("draft_must_be_unsent")
    )


async def _run(args: argparse.Namespace) -> int:
    api_key = os.environ.get(args.api_key_env, "").strip()
    if not api_key:
        raise SystemExit(f"{args.api_key_env} is required")
    cases = _load_cases(args.fixture)
    service = GeminiEmailAnalysisService(
        api_key=api_key,
        model=args.model,
        timeout_seconds=args.timeout,
        review_confidence_threshold=args.review_threshold,
        deadline_confidence_threshold=args.deadline_threshold,
    )
    passed = 0
    hard_gate_failed = False
    results: list[dict[str, object]] = []
    for case in cases:
        result = await service.analyze(_request(case))
        failures = _case_failures(
            case=case,
            result=result,
            link_confidence_threshold=args.review_threshold,
        )
        if not failures:
            passed += 1
        critical = _is_critical_safety_case(case)
        hard_failure = bool(
            "provider_status" in failures
            or (critical and failures)
        )
        hard_gate_failed = hard_gate_failed or hard_failure
        results.append(
            {
                "case_id": case["case_id"],
                "passed": not failures,
                "failures": failures,
                "provider_status": result.provider_status.value,
                "critical": critical,
                "hard_failure": hard_failure,
            }
        )
    pass_rate = passed / len(cases) if cases else 0.0
    print(
        json.dumps(
            {
                "model": args.model,
                "passed": passed,
                "total": len(cases),
                "pass_rate": round(pass_rate, 4),
                "required_pass_rate": args.min_pass_rate,
                "hard_gate_passed": not hard_gate_failed,
                "cases": results,
            },
            indent=2,
        )
    )
    return (
        0
        if pass_rate >= args.min_pass_rate and not hard_gate_failed
        else 1
    )


def main() -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm-live-provider", action="store_true")
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--api-key-env", default="GOOGLE_API_KEY")
    parser.add_argument("--model")
    parser.add_argument("--timeout", type=float)
    parser.add_argument("--review-threshold", type=float)
    parser.add_argument("--deadline-threshold", type=float)
    parser.add_argument("--min-pass-rate", type=float, default=0.9)
    args = parser.parse_args()
    if not args.confirm_live_provider:
        parser.error("--confirm-live-provider is required because this check is billable")
    if not 0.0 <= args.min_pass_rate <= 1.0:
        parser.error("--min-pass-rate must be between 0 and 1")
    args.model = args.model or settings.gemini_model
    args.timeout = (
        args.timeout
        if args.timeout is not None
        else settings.email_ai_analysis_timeout_seconds
    )
    args.review_threshold = (
        args.review_threshold
        if args.review_threshold is not None
        else settings.email_ai_auto_confidence_threshold
    )
    args.deadline_threshold = (
        args.deadline_threshold
        if args.deadline_threshold is not None
        else settings.email_ai_deadline_confidence_threshold
    )
    for label, value in (
        ("--review-threshold", args.review_threshold),
        ("--deadline-threshold", args.deadline_threshold),
    ):
        if not 0.0 <= value <= 1.0:
            parser.error(f"{label} must be between 0 and 1")
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
