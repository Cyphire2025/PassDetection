"""Keep editable single-variable template text acceptable to Meta."""


def normalize_template_text(value: str) -> str:
    """Flatten pasted whitespace, preserving words, punctuation and Unicode.

    The approved template supplies paragraph breaks around its variable. Newlines,
    tabs and excessive spaces inside that variable caused rejected reminder batches.
    """
    return " ".join(value.split())
