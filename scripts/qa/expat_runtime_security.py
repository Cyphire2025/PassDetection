"""Exercise the upstream Expat buffer-bound regression in the final image.

Based on the upstream regression introduced in 4d9b1c499ecb66323260a7274edcf86c5eab0517.
This qualification-only module has fixed library/symbol inputs and no service
endpoint. Refuse older versions before making intentionally invalid API calls.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import pyexpat


def require_patched_expat(version: tuple[int, ...]) -> None:
    if version < (2, 9, 0):
        raise RuntimeError("The XML buffer regression requires Expat 2.9.0 or later")


def probe_expat_security() -> dict[str, object]:
    require_patched_expat(pyexpat.version_info)
    library_name = ctypes.util.find_library("expat")
    if not library_name:
        raise RuntimeError("The reviewed shared XML library is missing")
    library = ctypes.CDLL(library_name)
    library.XML_ExpatVersion.argtypes, library.XML_ExpatVersion.restype = [], ctypes.c_char_p
    if library.XML_ExpatVersion().decode("ascii") != pyexpat.EXPAT_VERSION:
        raise RuntimeError("Python XML parsing uses a different Expat version")
    library.XML_ParserCreate.argtypes, library.XML_ParserCreate.restype = [ctypes.c_char_p], ctypes.c_void_p
    library.XML_ParserFree.argtypes, library.XML_ParserFree.restype = [ctypes.c_void_p], None
    library.XML_GetBuffer.argtypes, library.XML_GetBuffer.restype = [ctypes.c_void_p, ctypes.c_int], ctypes.c_void_p
    library.XML_ParseBuffer.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
    library.XML_ParseBuffer.restype = ctypes.c_int
    library.XML_GetErrorCode.argtypes, library.XML_GetErrorCode.restype = [ctypes.c_void_p], ctypes.c_int
    invalid_argument = pyexpat.errors.codes[pyexpat.errors.XML_ERROR_INVALID_ARGUMENT]
    for final in (0, 1):
        parser = library.XML_ParserCreate(None)
        if not parser:
            raise RuntimeError("XML parser allocation failed")
        try:
            buffer = library.XML_GetBuffer(parser, 10)
            if not buffer:
                raise RuntimeError("XML buffer allocation failed")
            if library.XML_ParseBuffer(parser, 10000, final) != 0 or library.XML_GetErrorCode(parser) != invalid_argument:
                raise RuntimeError("XML parser accepted a length beyond its allocated buffer")
            ctypes.memmove(buffer, b"<r></r>", 7)
            if library.XML_ParseBuffer(parser, 7, 0) != 1:
                raise RuntimeError("XML parser rejected the valid control document")
            if library.XML_ParseBuffer(parser, 10000, final) != 0 or library.XML_GetErrorCode(parser) != invalid_argument:
                raise RuntimeError("XML parser accepted a length beyond its remaining buffer")
        finally:
            library.XML_ParserFree(parser)
    return {"expat_buffer_bound_negatives": 4, "expat_valid_control_parses": 2}
