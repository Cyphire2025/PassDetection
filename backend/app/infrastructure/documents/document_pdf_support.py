"""Fail-closed, bounded PDF text extraction used by document matching."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from io import BytesIO
from typing import Any


@dataclass(frozen=True, slots=True)
class PdfProcessingLimits:
    max_ocr_pages: int
    max_ocr_pixels: int
    max_ocr_seconds: float
    max_page_text_chars: int
    max_pages_to_inspect: int
    max_parse_seconds: float
    max_source_bytes: int
    max_text_chars: int
    max_text_layer_pages: int
    max_total_pages: int
    ocr_render_scale: float


@dataclass(frozen=True, slots=True)
class _PdfTextRead:
    """Text plus the security decision needed before image-only OCR."""

    text: str
    safe_for_ocr: bool


class DocumentOcrUnavailableError(RuntimeError):
    """Image-only PDF OCR exhausted its bounded runtime and may be retried."""


def ocr_validated_image_only_pdf(
    content: bytes,
    *,
    pdfium: Any,
    limits: PdfProcessingLimits,
) -> str:
    """OCR content that already passed the active-PDF safety validation."""

    if pdfium is None or len(content) > limits.max_source_bytes:
        return ""
    started_at = time.monotonic()
    try:
        import pytesseract

        document = pdfium.PdfDocument(content)
        page_texts: list[str] = []
        text_length = 0
        page_count = min(len(document), limits.max_ocr_pages)
        for page_index in range(page_count):
            remaining_seconds = limits.max_ocr_seconds - (time.monotonic() - started_at)
            if remaining_seconds <= 0.25:
                break
            page = document[page_index]
            bitmap = page.render(scale=limits.ocr_render_scale)
            image = bitmap.to_pil()
            if image.width * image.height > limits.max_ocr_pixels:
                image.thumbnail((2000, 2000))
            try:
                page_text = pytesseract.image_to_string(
                    image,
                    lang="eng",
                    config="--oem 1 --psm 6",
                    timeout=max(0.25, remaining_seconds),
                )
            except RuntimeError as exc:
                if page_texts:
                    break
                raise DocumentOcrUnavailableError from exc
            normalized = "\n".join(
                " ".join(line.split()) for line in page_text.splitlines() if line.strip()
            )
            remaining_chars = limits.max_text_chars - text_length
            if remaining_chars <= 0:
                break
            page_texts.append(normalized[:remaining_chars])
            text_length += min(len(normalized), remaining_chars)
        return "\n".join(page_texts)[: limits.max_text_chars]
    except DocumentOcrUnavailableError:
        raise
    except Exception:
        # Rendering and OCR remain an optional, fail-closed fallback. The
        # isolated parser process owns the hard wall-time and memory caps.
        return ""


def read_pdf_text_with_pypdf(
    content: bytes,
    *,
    pdf_reader: Any,
    has_active_pdf_features: Callable[..., bool],
    extract_pdf_text_with_pdfium: Callable[..., str | None],
    limits: PdfProcessingLimits,
) -> _PdfTextRead:
    if pdf_reader is None or len(content) > limits.max_source_bytes:
        return _PdfTextRead("", False)
    try:
        started_at = time.monotonic()
        reader = pdf_reader(BytesIO(content), strict=False)
        if reader.is_encrypted or len(reader.pages) > limits.max_total_pages:
            return _PdfTextRead("", False)
        if has_active_pdf_features(
            reader,
            deadline=started_at + limits.max_parse_seconds,
        ):
            return _PdfTextRead("", False)

        # PDFium can determine whether a page has an embedded text layer
        # without decoding a full-page scan through pypdf's layout extractor.
        pdfium_text = extract_pdf_text_with_pdfium(
            content,
            deadline=started_at + limits.max_parse_seconds,
        )
        if pdfium_text is not None:
            # An empty result explicitly selects image OCR; native text is final.
            return _PdfTextRead(pdfium_text, True)

        page_texts: list[str] = []
        text_length = 0
        for page in reader.pages[: limits.max_pages_to_inspect]:
            if time.monotonic() - started_at > limits.max_parse_seconds:
                return _PdfTextRead("", False)
            page_text = (page.extract_text() or "")[: limits.max_page_text_chars]
            if time.monotonic() - started_at > limits.max_parse_seconds:
                return _PdfTextRead("", False)
            if not page_text:
                continue
            normalized_lines = [
                " ".join(line.split()) for line in page_text.splitlines() if line.strip()
            ]
            normalized = "\n".join(normalized_lines)
            remaining = limits.max_text_chars - text_length
            if remaining <= 0:
                break
            page_texts.append(normalized[:remaining])
            text_length += min(len(normalized), remaining)
        return _PdfTextRead(
            "\n".join(page_texts)[: limits.max_text_chars],
            True,
        )
    except Exception:
        # Malformed, encrypted, or unreadable PDFs fail closed.
        return _PdfTextRead("", False)


def extract_pdf_text_with_pdfium(
    content: bytes,
    *,
    pdfium: Any,
    deadline: float,
    limits: PdfProcessingLimits,
) -> str | None:
    """Return bounded embedded text, or None when PDFium is unavailable."""

    if pdfium is None:
        return None
    try:
        document = pdfium.PdfDocument(content)
        page_texts: list[str] = []
        text_length = 0
        for page_index in range(min(len(document), limits.max_text_layer_pages)):
            if time.monotonic() > deadline:
                return None
            page = document[page_index]
            text_page = page.get_textpage()
            page_text = text_page.get_text_range()[: limits.max_page_text_chars]
            normalized = "\n".join(
                " ".join(line.split()) for line in page_text.splitlines() if line.strip()
            )
            remaining = limits.max_text_chars - text_length
            if remaining <= 0:
                break
            page_texts.append(normalized[:remaining])
            text_length += min(len(normalized), remaining)
        return "\n".join(page_texts)[: limits.max_text_chars]
    except Exception:
        # pypdf remains the compatibility fallback for valid PDFs PDFium cannot decode.
        return None


def has_active_pdf_features(
    reader: Any,
    *,
    deadline: float | None,
    resolve_object: Callable[[Any], Any],
    fields_have_actions: Callable[..., bool],
    action_is_active: Callable[..., bool],
) -> bool:
    """Reject executable, auto-action, attachment, and XFA PDF features."""

    root = resolve_object(reader.root_object)
    if not isinstance(root, Mapping):
        return True
    if any(
        key in root
        for key in ("/OpenAction", "/AA", "/AF", "/Collection", "/JavaScript", "/JS")
    ):
        return True

    names = resolve_object(root.get("/Names"))
    if isinstance(names, Mapping) and any(
        key in names for key in ("/JavaScript", "/JS", "/EmbeddedFiles")
    ):
        return True

    acro_form = resolve_object(root.get("/AcroForm"))
    if isinstance(acro_form, Mapping):
        if "/XFA" in acro_form or "/AA" in acro_form:
            return True
        if fields_have_actions(acro_form.get("/Fields"), deadline=deadline):
            return True

    for page in reader.pages:
        if deadline is not None and time.monotonic() > deadline:
            return True
        page_object = resolve_object(page)
        if not isinstance(page_object, Mapping):
            return True
        if "/AA" in page_object or "/AF" in page_object:
            return True
        annotations = resolve_object(page_object.get("/Annots"))
        if annotations is None:
            continue
        if not isinstance(annotations, (list, tuple)):
            return True
        for annotation_reference in annotations:
            annotation = resolve_object(annotation_reference)
            if not isinstance(annotation, Mapping):
                return True
            if str(annotation.get("/Subtype", "")) in {"/FileAttachment", "/RichMedia"}:
                return True
            if "/AA" in annotation or action_is_active(
                annotation.get("/A"),
                deadline=deadline,
            ):
                return True
    return False


def pdf_fields_have_actions(
    fields_reference: Any,
    *,
    deadline: float | None,
    resolve_object: Callable[[Any], Any],
    action_is_active: Callable[..., bool],
) -> bool:
    fields = resolve_object(fields_reference)
    if fields is None:
        return False
    if not isinstance(fields, (list, tuple)):
        return True
    stack = list(fields)
    visited = 0
    while stack:
        visited += 1
        if visited > 10_000 or (deadline is not None and time.monotonic() > deadline):
            return True
        field = resolve_object(stack.pop())
        if not isinstance(field, Mapping):
            return True
        if "/AA" in field or action_is_active(field.get("/A"), deadline=deadline):
            return True
        children = resolve_object(field.get("/Kids"))
        if children is None:
            continue
        if not isinstance(children, (list, tuple)):
            return True
        stack.extend(children)
    return False


def pdf_action_is_active(
    action_reference: Any,
    *,
    deadline: float | None,
    resolve_object: Callable[[Any], Any],
) -> bool:
    if action_reference is None:
        return False
    stack = [action_reference]
    visited = 0
    while stack:
        visited += 1
        if visited > 1_000 or (deadline is not None and time.monotonic() > deadline):
            return True
        action = resolve_object(stack.pop())
        if not isinstance(action, Mapping):
            return True
        if "/JS" in action or "/JavaScript" in action or "/Launch" in action:
            return True
        if str(action.get("/S", "")) in {
            "/JavaScript",
            "/Launch",
            "/SubmitForm",
            "/ImportData",
            "/GoToR",
            "/Rendition",
            "/RichMediaExecute",
        }:
            return True
        next_action = resolve_object(action.get("/Next"))
        if next_action is None:
            continue
        if isinstance(next_action, (list, tuple)):
            stack.extend(next_action)
        else:
            stack.append(next_action)
    return False


def resolved_pdf_object(value: Any) -> Any:
    if value is None:
        return None
    resolver = getattr(value, "get_object", None)
    return resolver() if callable(resolver) else value
