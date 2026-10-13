"""Recognize two PostgreSQL dump/restore deparse rewrites, only in rehearsal.

This is not SQL equivalence checking. Only literal unbounded varchar-array to
text-array casts and pure parenthesized AND association may differ. Migration
preservation compares actual restored catalog and row/ACL hashes exactly.
"""

from __future__ import annotations

import re
from typing import Any

MAX_DEFINITION_BYTES = 64 * 1024
MAX_CATALOG_DEFINITION_BYTES = 4 * 1024 * 1024
_TOKEN = re.compile(r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|[A-Za-z_][A-Za-z_0-9$]*|::|.", re.DOTALL)
_LITERAL = re.compile(r"'(?:''|[^'])*'", re.DOTALL)


def _literal_array_cast(tokens: list[str], start: int) -> tuple[int, str] | None:
    if tokens[start:start + 3] != ["(", "ARRAY", "["]:
        return None
    # A function's argument parentheses are not grouping parentheses. For
    # example fn(ARRAY[...])::text[] casts fn's result, not its argument.
    if start and (tokens[start - 1][0].isalnum() or tokens[start - 1][0] in '_"$'):
        return None
    index, values = start + 3, []
    while index < len(tokens):
        if (_LITERAL.fullmatch(tokens[index]) is None
                or tokens[index + 1:index + 3] != ["::", "charactervarying"]):
            return None
        values.append(f"({tokens[index]}::charactervarying)::text")
        index += 3
        if tokens[index:index + 1] == [","]:
            index += 1
            continue
        if tokens[index:index + 6] == ["]", ")", "::", "text", "[", "]"]:
            return index + 6, "ARRAY[" + ",".join(values) + "]"
        return None
    return None


def _tokens(definition: str) -> list[str]:
    if len(definition.encode("utf-8")) > MAX_DEFINITION_BYTES:
        raise ValueError("restore_definition_size_limit")
    tokens = _TOKEN.findall(definition)
    if any(token in {"'", '"'} for token in tokens):
        raise ValueError("restore_definition_unterminated_quote")
    return tokens


def normalize_literal_array_casts(definition: str) -> str:
    """O(L) time/space, with at most 64 KiB of deparsed SQL per definition."""
    tokens = _tokens(definition)
    result, index = [], 0
    while index < len(tokens):
        match = _literal_array_cast(tokens, index)
        if match is None:
            result.append(tokens[index])
            index += 1
        else:
            index, replacement = match
            result.append(replacement)
    return "".join(result)


def _parenthesis_ends(tokens: list[str]) -> dict[int, int]:
    stack: list[int] = []
    ends: dict[int, int] = {}
    for index, token in enumerate(tokens):
        if token == "(":
            stack.append(index)
        elif token == ")":
            if not stack:
                raise ValueError("restore_definition_unbalanced_parentheses")
            ends[stack.pop()] = index
    if stack:
        raise ValueError("restore_definition_unbalanced_parentheses")
    return ends


def _boolean_group(
    tokens: list[str], start: int, ends: dict[int, int],
) -> tuple[str, list[int]] | None:
    """Only whole parenthesized operands, joined by one exact Boolean operator."""
    end, cursor, operator = ends[start], start + 1, ""
    children: list[int] = []
    while cursor < end:
        if tokens[cursor] != "(":
            return None
        children.append(cursor)
        cursor = ends[cursor] + 1
        if cursor == end:
            return operator, children
        if tokens[cursor] not in {"AND", "OR"} or (operator and tokens[cursor] != operator):
            return None
        operator = tokens[cursor]
        cursor += 1
    return None


def normalize_associative_and(definition: str) -> str:
    """O(L) time/space: index spans, mark removed delimiters, serialize once.

    Enter only a complete CHECK body and pure Boolean groups. A function, NOT,
    mixed operators, arithmetic, cast or comparison is an opaque leaf. Preserve
    OR grouping, single wrappers, operand order, duplicates and every leaf byte.
    """
    tokens = _tokens(definition)
    if tokens[:2] != ["CHECK", "("]:
        return definition
    ends = _parenthesis_ends(tokens)
    if ends[1] != len(tokens) - 1:
        return definition
    pending = [1]
    removed: set[int] = set()
    groups: dict[int, tuple[str, list[int]] | None] = {}

    def group(start: int) -> tuple[str, list[int]] | None:
        if start not in groups:
            groups[start] = _boolean_group(tokens, start, ends)
        return groups[start]

    while pending:
        current = group(pending.pop())
        if current is None:
            continue
        operator, children = current
        for child in children:
            nested = group(child)
            if operator == "AND" and nested is not None and nested[0] == "AND":
                removed.update((child, ends[child]))
            pending.append(child)
    return "".join(token for index, token in enumerate(tokens) if index not in removed)


def _restore_comparison(snapshot: dict[str, Any]) -> dict[str, Any]:
    catalog: dict[str, Any] = {}
    total = 0
    for name, table in snapshot["catalog"].items():
        catalog[name] = {**table}
        for kind in ("constraints", "indexes"):
            definitions = []
            for row in table[kind]:
                definition = row[-1]
                total += len(definition.encode("utf-8"))
                if total > MAX_CATALOG_DEFINITION_BYTES:
                    raise ValueError("restore_catalog_definition_size_limit")
                normalized = normalize_literal_array_casts(definition)
                if kind == "constraints":
                    normalized = normalize_associative_and(normalized)
                definitions.append([*row[:-1], normalized])
            catalog[name][kind] = definitions
    return {**snapshot, "catalog": catalog}


def restored_baseline(before: dict[str, Any], restored: dict[str, Any]) -> dict[str, Any]:
    """Approve only the known restore representation, then retain exact reality.

    Row hashes, grants, owners, column defaults and all other fields remain exact.
    The returned object has never been normalized and becomes the helper's
    pre-migration baseline, so every subsequent migration comparison is strict.
    """
    if _restore_comparison(before) != _restore_comparison(restored):
        raise AssertionError("Restored 0129 rows, ACLs or schema differ from the populated backup")
    return restored
