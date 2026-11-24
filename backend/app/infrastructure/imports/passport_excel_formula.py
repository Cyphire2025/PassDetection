"""Stream worksheet formula tags without assuming namespace or chunk lengths."""

from typing import NoReturn, Protocol
from xml.parsers import expat


class WorkbookXMLParseError(ValueError):
    """A worksheet cannot be safely inspected as OpenXML."""


class _FormulaFound(Exception):
    pass


class WorkbookXMLSource(Protocol):
    def read(self, size: int = -1, /) -> bytes: ...


def worksheet_contains_formula(source: WorkbookXMLSource) -> bool:
    """Inspect start events without building an element tree or loading entities.

    Expat retains split XML tokens, including arbitrarily qualified names. The
    caller enforces the archive's total expansion limit before opening a member.
    """
    parser = expat.ParserCreate(namespace_separator="}")

    def start_element(name: str, _attributes: dict[str, str]) -> None:
        if name.rsplit("}", 1)[-1] == "f":
            raise _FormulaFound

    def reject_entity(*_arguments: object) -> NoReturn:
        raise WorkbookXMLParseError("Worksheet entity declarations are unsupported")

    parser.StartElementHandler = start_element
    parser.EntityDeclHandler = reject_entity
    parser.ExternalEntityRefHandler = reject_entity
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    try:
        while chunk := source.read(64 * 1024):
            parser.Parse(chunk, False)
        parser.Parse(b"", True)
    except _FormulaFound:
        return True
    except expat.ExpatError as exc:
        raise WorkbookXMLParseError("The worksheet XML could not be read") from exc
    return False
