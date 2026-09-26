"""Permit only the reviewed constant GNU allocator-reclaim call in application code.

This is not a ctypes allowlist by module name. Both the complete immutable source
and the complete function AST are pinned; a source change needs another review.
The GNU-presence check does not invoke a data-processing function. The only
foreign call is malloc_trim(0), declared as size_t -> int, with no input bytes,
library path, symbol name, or flags supplied by a request or configuration.
"""
from __future__ import annotations

import ast
import hashlib
from pathlib import PurePosixPath

REVIEWED_PATH = "/app/app/core/native_image_admission.py"
REVIEWED_SOURCE_SHA256 = "8ec758c93c7424730e115d99dcbbdc5f3a0835534465f5380c0c2bbccd633e09"
REVIEWED_FUNCTION_AST_SHA256 = "398bbab1e1fcaa94ab8cff874b1b6a0b17a432527287da09436fdaa54c2e2275"


def reviewed_allocator_source(path: str, source: bytes) -> dict[str, str] | None:
    if path != REVIEWED_PATH or str(PurePosixPath(path)) != path:
        return None
    digest = hashlib.sha256(source).hexdigest()
    if digest != REVIEWED_SOURCE_SHA256:
        return None
    try:
        tree = ast.parse(source)
    except (SyntaxError, UnicodeError, ValueError):
        return None
    functions = [node for node in tree.body
                 if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and node.name == "_heap_reclaimer"]
    if len(functions) != 1:
        return None
    syntax_digest = hashlib.sha256(ast.dump(functions[0], include_attributes=False).encode()).hexdigest()
    if syntax_digest != REVIEWED_FUNCTION_AST_SHA256:
        return None
    return {"file": path, "source_sha256": digest, "function_ast_sha256": syntax_digest,
            "library": "current process (ctypes.CDLL(None))",
            "gnu_presence_check": "getattr(library, 'gnu_get_libc_version')",
            "call": "malloc_trim(0)", "argument_types": "[ctypes.c_size_t]",
            "return_type": "ctypes.c_int", "request_controlled_arguments": "none"}
