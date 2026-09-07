"""Public place projection used by the trip globe; never an inferred airport."""

from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator


class JourneyDestination(BaseModel):
    label: str = Field(min_length=1, max_length=255)
    country: str = Field(min_length=1, max_length=160)
    country_code: str = Field(pattern=r"^[A-Z]{2}$")
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    place_type: Literal["country", "state", "city"]


class MobileJourneyDestinationResponse(BaseModel):
    status: Literal["resolved", "not_found", "ambiguous", "unavailable", "not_configured"]
    destination: JourneyDestination | None = None
    attribution: Literal["© OpenStreetMap contributors"] = "© OpenStreetMap contributors"
    attribution_url: Literal["https://www.openstreetmap.org/copyright"] = (
        "https://www.openstreetmap.org/copyright"
    )
    retry_after_seconds: int | None = Field(default=None, ge=1, le=86_400)

    @model_validator(mode="after")
    def validate_resolution(self) -> Self:
        if (self.status == "resolved") != (self.destination is not None):
            raise ValueError("Coordinates require a resolved destination")
        return self
