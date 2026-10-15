"""Staff history projections intentionally exclude passport fields and assets."""

import uuid
from datetime import date

from pydantic import BaseModel


class CompanyTravellerResponse(BaseModel):
    id: uuid.UUID
    display_name: str
    participation_count: int
    last_trip_date: date | None
    status: str


class CompanyTravellerPage(BaseModel):
    items: list[CompanyTravellerResponse]
    next_cursor: str | None


class TravellerHistoryResponse(BaseModel):
    id: uuid.UUID
    group_id: uuid.UUID
    group_name: str
    travel_date: date | None
    lifecycle: str
    participation_status: str
    document_revision: int | None


class TravellerHistoryPage(BaseModel):
    items: list[TravellerHistoryResponse]
    next_cursor: str | None
