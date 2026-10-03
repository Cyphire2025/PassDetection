"""Exact upload descriptors; transfer capabilities never select ambient accounts."""

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MCPNativeUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    purpose: Literal["contact_broadcast", "group_workbook", "document_pdf"]
    agency_id: uuid.UUID
    group_id: uuid.UUID | None = None
    document_type: (
        Literal[
            "visa",
            "flight_ticket",
            "flight_ticket_arrival",
            "flight_ticket_domestic",
            "flight_ticket_domestic_arrival",
            "other",
        ]
        | None
    ) = None
    filename: str = Field(min_length=1, max_length=120)
    byte_size: int = Field(ge=1, strict=True)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def exact_lane(self):
        if self.purpose in {"group_workbook", "document_pdf"} and self.group_id is None:
            raise ValueError("Choose the exact target group")
        if self.purpose == "contact_broadcast" and self.group_id is not None:
            raise ValueError("A contact workbook is agency-scoped")
        if (self.purpose == "document_pdf") != (self.document_type is not None):
            raise ValueError("A document PDF requires its exact document lane")
        extension = ".pdf" if self.purpose == "document_pdf" else ".xlsx"
        if (
            not self.filename.lower().endswith(extension)
            or any(ord(c) < 32 for c in self.filename)
            or any(c in self.filename for c in ("/", "\\", '"'))
        ):
            raise ValueError("Use a plain filename with the matching extension")
        return self


class MCPNativeDeliveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    byte_size: int = Field(ge=1, strict=True)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
