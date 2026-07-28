from app.application.use_cases.email_integrations.relevance import decide_relevance


def test_recognized_travel_document_is_relevant() -> None:
    decision = decide_relevance(
        subject="Your booking",
        body_text="Please see attached.",
        attachment_filenames=["ASHA_TICKET.pdf"],
        detected_document_types=["flight_ticket"],
        deterministic_match_evidence=["passport_number_exact"],
    )

    assert decision.status == "relevant"
    assert decision.confidence == 0.98
    assert decision.should_retrieve is True
    assert "document_type_flight_ticket" in decision.evidence


def test_unknown_document_attachment_is_held_for_review() -> None:
    decision = decide_relevance(
        subject="Documents",
        body_text="Attached",
        attachment_filenames=["scan.pdf"],
        detected_document_types=["unknown"],
    )

    assert decision.status == "possibly_relevant"
    assert decision.should_retrieve is True


def test_unrelated_mail_without_operational_signals_is_ignored() -> None:
    decision = decide_relevance(
        subject="Office lunch",
        body_text="The menu is attached below.",
        attachment_filenames=[],
        detected_document_types=[],
    )

    assert decision.status == "unrelated"
    assert decision.should_retrieve is False
