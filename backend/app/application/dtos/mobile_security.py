"""Validated attestation and device registration inputs, independent of HTTP."""
from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class MobileIntegrityChallengeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["play_integrity", "app_attest"]
    action: Literal["document_download_authorize", "app_attest_key_register"]
    request_hash: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")
    installation_id: str = Field(min_length=16, max_length=128)
    key_id: str | None = Field(
        default=None,
        min_length=32,
        max_length=512,
        pattern=r"^[A-Za-z0-9_+/=-]+$",
    )

    @model_validator(mode="after")
    def validate_provider_shape(self) -> MobileIntegrityChallengeRequest:
        if self.provider == "play_integrity" and self.key_id is not None:
            raise ValueError("Play Integrity challenges do not use an App Attest key")
        if self.provider == "app_attest" and self.key_id is None:
            raise ValueError("App Attest challenges require a key identifier")
        if self.action == "app_attest_key_register" and self.provider != "app_attest":
            raise ValueError("Only App Attest can register an Apple key")
        return self


class MobileIntegrityProofRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    challenge_id: uuid.UUID
    provider: Literal["play_integrity", "app_attest"]
    proof: str = Field(min_length=16, max_length=65_536)
    installation_id: str = Field(min_length=16, max_length=128)
    key_id: str | None = Field(
        default=None,
        min_length=32,
        max_length=512,
        pattern=r"^[A-Za-z0-9_+/=-]+$",
    )

    @model_validator(mode="after")
    def validate_provider_shape(self) -> MobileIntegrityProofRequest:
        if self.provider == "play_integrity" and self.key_id is not None:
            raise ValueError("Play Integrity proofs do not use an App Attest key")
        if self.provider == "app_attest" and self.key_id is None:
            raise ValueError("App Attest proofs require a key identifier")
        return self


class MobileAppAttestRegistrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    challenge_id: uuid.UUID
    installation_id: str = Field(min_length=16, max_length=128)
    key_id: str = Field(
        min_length=32,
        max_length=512,
        pattern=r"^[A-Za-z0-9_+/=-]+$",
    )
    attestation_object: str = Field(min_length=32, max_length=65_536)


class MobilePushRegistrationRequest(BaseModel):
    provider: Literal["expo", "fcm", "apns"]
    push_token: str = Field(min_length=16, max_length=512)
    installation_id: str = Field(min_length=16, max_length=128)
    apns_environment: Literal["development", "production"] | None = None

    @model_validator(mode="after")
    def validate_native_push_registration(self) -> MobilePushRegistrationRequest:
        if self.provider == "apns":
            if self.apns_environment is None:
                raise ValueError("APNs registration requires the signed provisioning environment")
            if (
                len(self.push_token) % 2
                or any(char not in "0123456789abcdefABCDEF" for char in self.push_token)
            ):
                raise ValueError("APNs requires a hexadecimal native device token")
            self.push_token = self.push_token.lower()
        elif self.apns_environment is not None:
            raise ValueError("APNs environment is only valid for APNs registrations")
        if any(char.isspace() for char in self.push_token):
            raise ValueError("Push token must not contain whitespace")
        return self

    @field_validator("push_token", mode="before")
    @classmethod
    def normalize_push_token(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value
