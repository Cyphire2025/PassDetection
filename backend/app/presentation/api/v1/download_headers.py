"""HTTP attachment filenames without raw Unicode or header delimiters."""

from urllib.parse import quote


def attachment_disposition(filename: str) -> str:
    """Preserve simple filenames and encode other names using RFC 5987."""
    if filename and all(
        32 <= ord(character) < 127 and character not in {'"', "\\"} for character in filename
    ):
        return f'attachment; filename="{filename}"'
    return f"attachment; filename*=UTF-8''{quote(filename, safe='')}"
