"""Value-free task failure projections for logs, events and result metadata."""

from __future__ import annotations

from dataclasses import dataclass
from types import TracebackType

from app.core.logging.exception_diagnostics import diagnostic_frames
from app.core.logging.exception_diagnostics import diagnostic_name as diagnostic_name

PRIVATE_ARGUMENTS = "<private task arguments>"
_WHATSAPP_CODES = frozenset(
    {
        "WHATSAPP_PROVIDER_ERROR",
        "WHATSAPP_PROVIDER_NOT_CONFIGURED",
        "WHATSAPP_TEMPLATE_PAYLOAD_INVALID",
        "WHATSAPP_PROVIDER_UNREACHABLE",
        "WHATSAPP_DELIVERY_UNKNOWN",
        "WHATSAPP_PROVIDER_RATE_LIMITED",
        "WHATSAPP_PROVIDER_AUTH_FAILED",
        "WHATSAPP_PROVIDER_REJECTED",
        "WHATSAPP_PROVIDER_RESPONSE_INVALID",
        "WHATSAPP_MEDIA_UPLOAD_UNREACHABLE",
        "WHATSAPP_MEDIA_UPLOAD_INTERRUPTED",
        "WHATSAPP_MEDIA_UPLOAD_REJECTED",
        "WHATSAPP_DOCUMENT_INVALID",
        "WHATSAPP_DOCUMENT_UPLOAD_UNREACHABLE",
        "WHATSAPP_DOCUMENT_UPLOAD_INTERRUPTED",
        "WHATSAPP_DOCUMENT_UPLOAD_REJECTED",
    }
)


def _frames(trace: TracebackType | None) -> str:
    return diagnostic_frames(trace, unavailable="No task stack frames available")


@dataclass(frozen=True, slots=True)
class TaskFailureDiagnostic:
    exception_type: str
    exception_module: str
    message: str
    traceback: str
    code: str | None = None

    def exception_payload(self) -> dict[str, object]:
        # Keep Celery's JSON exception schema and original type identity. The
        # original exception and its args are never changed in the task process.
        return {
            "exc_type": self.exception_type,
            "exc_module": self.exception_module,
            "exc_message": (self.message,),
        }


def task_failure_diagnostic(error: BaseException | None) -> TaskFailureDiagnostic:
    error_type = (
        diagnostic_name(type(error).__qualname__, "Exception") if error is not None else "Exception"
    )
    module = (
        diagnostic_name(type(error).__module__, "builtins") if error is not None else "builtins"
    )
    code = None
    if (
        module == "app.infrastructure.whatsapp.provider_errors"
        and error_type == "WhatsAppCloudApiError"
    ):
        candidate = getattr(error, "code", None)
        if isinstance(candidate, str) and candidate in _WHATSAPP_CODES:
            code = candidate
    message = f"{code or error_type}: private task failure details withheld"
    return TaskFailureDiagnostic(
        error_type,
        module,
        message,
        _frames(error.__traceback__ if error is not None else None),
        code,
    )
