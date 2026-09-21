"""Keep human document-type approval separate from passenger-match evidence."""

MANUAL_DOCUMENT_TYPE_APPROVAL_PREFIX = "Document type manually approved; "


def has_manual_document_type_approval(reason: str | None) -> bool:
    return bool(reason and reason.startswith(MANUAL_DOCUMENT_TYPE_APPROVAL_PREFIX))


def preserve_document_type_approval(
    approval_reason: str | None,
    match_reason: str | None,
) -> str | None:
    if not has_manual_document_type_approval(approval_reason):
        return match_reason
    if has_manual_document_type_approval(match_reason):
        return match_reason
    return MANUAL_DOCUMENT_TYPE_APPROVAL_PREFIX + (match_reason or "Passenger match retained")
