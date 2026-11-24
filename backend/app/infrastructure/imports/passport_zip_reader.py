"""Read one admitted archive member at a time into canonical request staging."""

from __future__ import annotations

import zipfile

from app.infrastructure.imports.passport_document_images import validate_passport_document_image
from app.infrastructure.imports.passport_document_streams import (
    MAX_MEMBER_BYTES,
    PassportDocumentStagingError,
    _read_forward_stream_exact,
)
from app.infrastructure.imports.passport_document_workspace import (
    PassportDocumentFile,
    PassportDocumentImportWorkspace,
    PassportDocumentUploadSource,
    RejectedPassportDocument,
)
from app.infrastructure.imports.passport_zip_admission import (
    PassportZipMemberLimitError,
    admit_passport_zip_directory,
)
from app.infrastructure.imports.passport_zip_members import _ImportBudget, admit_passport_zip_member
from app.infrastructure.security.upload_validator import UploadValidator


def collect_passport_zip(
    validator: UploadValidator,
    source: PassportDocumentUploadSource,
    *,
    workspace: PassportDocumentImportWorkspace,
    budget: _ImportBudget,
    allowed_staff_codes: set[str] | None,
    max_members: int,
) -> tuple[list[PassportDocumentFile], list[RejectedPassportDocument]]:
    accepted: list[PassportDocumentFile] = []
    rejected: list[RejectedPassportDocument] = []
    try:
        source.stream.seek(0)
        admit_passport_zip_directory(source.stream, max_members=max_members)
        with zipfile.ZipFile(source.stream) as archive:
            members = archive.infolist()
            if len(members) > max_members:
                return (
                    accepted,
                    [
                        RejectedPassportDocument(
                            source.filename, f"ZIP contains more than {max_members} entries"
                        )
                    ],
                )
            if any((info.flag_bits & 1 for info in members)):
                return (
                    accepted,
                    [
                        RejectedPassportDocument(
                            source.filename, "Encrypted ZIP archives are not allowed"
                        )
                    ],
                )
            for info in members:
                selection = admit_passport_zip_member(
                    info,
                    source_filename=source.filename,
                    budget=budget,
                    allowed_staff_codes=allowed_staff_codes,
                )
                if isinstance(selection, RejectedPassportDocument):
                    rejected.append(selection)
                    continue
                if selection is None:
                    continue
                basename = selection
                with archive.open(info) as member:
                    member_content = _read_forward_stream_exact(
                        member,
                        expected_bytes=info.file_size,
                        maximum_bytes=MAX_MEMBER_BYTES,
                        label="ZIP member",
                    )
                accepted_part, rejected_part = validate_passport_document_image(
                    validator,
                    filename=basename,
                    content=member_content,
                    declared_type=None,
                    workspace=workspace,
                    allowed_staff_codes=allowed_staff_codes,
                )
                accepted.extend(accepted_part)
                rejected.extend(rejected_part)
    except PassportZipMemberLimitError as exc:
        rejected.append(RejectedPassportDocument(source.filename, str(exc)))
    except PassportDocumentStagingError as exc:
        rejected.append(RejectedPassportDocument(source.filename, str(exc)))
    except (OSError, ValueError, zipfile.BadZipFile, RuntimeError):
        rejected.append(
            RejectedPassportDocument(source.filename, "Unreadable or encrypted ZIP archive")
        )
    finally:
        source.stream.seek(0)
    return (accepted, rejected)
