"""Cached Photon place resolution with deployment-wide upstream admission.

Only the saved, authorized destination is sent to Photon. Cache keys are shared
by normalized place text, never by passenger/account, and contain no plain text.
The security Redis owns the upstream lease so cache eviction cannot remove it.
Provider failure never causes a local or guessed coordinate fallback.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import secrets
import unicodedata
from collections.abc import AsyncIterator
from typing import Any, Literal, cast

import httpx
from pydantic import ValidationError
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.application.mobile.journey_destination import (
    JourneyDestination,
    MobileJourneyDestinationResponse,
)
from app.core.config.settings import MobileSettings, get_settings

_COOLDOWN = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('PEXPIRE', KEYS[1], ARGV[2])
end
return 0
"""
_PROVIDER_LEASE_KEY = "mobile-journey:photon:upstream:v1"
_MAX_RESPONSE_BYTES = 131_072
_COUNTRY_ALIASES = {
    "united arab emirates": "ae",
    "uae": "ae",
    "united kingdom": "gb",
    "uk": "gb",
    "united states of america": "us",
    "united states": "us",
    "usa": "us",
}
_COUNTRY_NAMES = {"ae": "United Arab Emirates", "gb": "United Kingdom", "us": "United States"}
_PLACE_ALIASES = {"hongkong": "hong kong"}


def _normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _canonical_place(value: str) -> str:
    normalized = _normalize(value)
    # Explicit spelling variants only; do not turn typo tolerance into guessed places.
    for alias, name in _PLACE_ALIASES.items():
        normalized = re.sub(rf"\b{re.escape(alias)}\b", name, normalized)
    return normalized


def _query(value: str | None) -> str | None:
    if not value or len(value) > 255:
        return None
    # The destination field represents a place, not an address or personal data.
    # Reject accidental emails, phone numbers, URLs, and multi-stop routes.
    if any(character.isdigit() for character in value) or any(
        character in value for character in "@:/\\;<>\n\r"
    ):
        return None
    normalized = _normalize(value)
    return normalized if len(normalized) >= 2 else None


def _words(value: str) -> str:
    result = " ".join(re.findall(r"[^\W_]+", _canonical_place(value)))
    for alias, code in _COUNTRY_ALIASES.items():
        if result == alias:
            return code
        if result.endswith(" " + alias):
            return result[: -len(alias)] + code
    return result


def _search_params(query: str) -> list[tuple[str, str]]:
    words = _words(query)
    suffix = words.rsplit(" ", 1)[-1]
    params = [("q", _canonical_place(query)), ("lang", "en"), ("limit", "8")]
    layers: tuple[str, ...] = ("country", "state", "city")
    if suffix in _COUNTRY_NAMES:
        # Photon can interpret 'UAE' as fuzzy Ukrainian text. Expand known
        # country aliases and apply its documented hard countrycode filter.
        params[0] = ("q", words[: -(len(suffix) + 1)] or _COUNTRY_NAMES[suffix])
        params.append(("countrycode", suffix.upper()))
        if words == suffix:
            layers = ("country",)
    return params + [("layer", layer) for layer in layers]


def _candidate(feature: object, query: str) -> tuple[JourneyDestination, int] | None:
    if not isinstance(feature, dict):
        return None
    properties, geometry = feature.get("properties"), feature.get("geometry")
    if not isinstance(properties, dict) or not isinstance(geometry, dict):
        return None
    place_type = properties.get("type")
    if (
        not isinstance(place_type, str)
        or place_type not in {"country", "state", "city"}
        or geometry.get("type") != "Point"
    ):
        return None
    name, country = properties.get("name"), properties.get("country")
    country_code, coordinates = properties.get("countrycode"), geometry.get("coordinates")
    if (
        not isinstance(name, str)
        or not name.strip()
        or not isinstance(country, str)
        or not country.strip()
        or not isinstance(country_code, str)
        or not country_code.strip()
    ):
        return None
    if not isinstance(coordinates, list) or len(coordinates) != 2:
        return None
    if any(isinstance(item, bool) or not isinstance(item, (float, int)) for item in coordinates):
        return None
    # Photon is typo tolerant. A globe must not silently accept a fuzzy place.
    # Require the full place name plus, when supplied, matching state/country.
    name_words = _words(name)
    state = properties.get("state")
    context = [state] if isinstance(state, str) else []
    context += [country, country_code]
    accepted = {name_words}
    for suffix in context:
        accepted.add(_words(f"{name}, {suffix}"))
    if isinstance(state, str):
        accepted.add(_words(f"{name}, {state}, {country}"))
        accepted.add(_words(f"{name}, {state}, {country_code}"))
    if place_type == "country":
        accepted.add(_words(country_code))
    if _words(query) not in accepted:
        return None
    try:
        destination = JourneyDestination(
            label=name.strip(),
            country=country.strip(),
            country_code=country_code.upper(),
            latitude=coordinates[1],
            longitude=coordinates[0],
            place_type=cast(Literal["country", "state", "city"], place_type),
        )
    except ValidationError:
        return None
    # A village with the same name must not displace a country/state/major city.
    osm_value = properties.get("osm_value")
    rank = 0 if isinstance(osm_value, str) and osm_value in {"village", "hamlet"} else 1
    return destination, rank


def select_destination(payload: object, query: str) -> MobileJourneyDestinationResponse:
    if not isinstance(payload, dict) or not isinstance(payload.get("features"), list):
        return MobileJourneyDestinationResponse(status="unavailable")
    features = payload["features"]
    if len(features) > 20:
        return MobileJourneyDestinationResponse(status="unavailable")
    candidates = [match for feature in features if (match := _candidate(feature, query))]
    if not candidates:
        return MobileJourneyDestinationResponse(status="not_found")
    rank = max(item[1] for item in candidates)
    matches = [item[0] for item in candidates if item[1] == rank]
    countries = [item for item in matches if item.place_type == "country"]
    if countries:
        matches = [
            item
            for item in matches
            if item.place_type != "city"
            or not any(
                item.country_code == country.country_code
                and _words(item.label) == _words(country.label)
                for country in countries
            )
        ]
    # A city and its enclosing same-named state (Dubai, Singapore etc.) describe
    # the same destination. Prefer the city point without inventing an airport.
    cities = [item for item in matches if item.place_type == "city"]
    if cities:
        matches = [
            item
            for item in matches
            if item.place_type != "state"
            or not any(
                item.country_code == city.country_code and _words(item.label) == _words(city.label)
                for city in cities
            )
        ]
    distinct: list[JourneyDestination] = []
    for item in matches:
        if not any(
            item.country_code == other.country_code
            and item.place_type == other.place_type
            and _words(item.label) == _words(other.label)
            and abs(item.latitude - other.latitude) < 0.02
            and abs(item.longitude - other.longitude) < 0.02
            for other in distinct
        ):
            distinct.append(item)
    if len(distinct) != 1:
        return MobileJourneyDestinationResponse(status="ambiguous")
    return MobileJourneyDestinationResponse(status="resolved", destination=distinct[0])


class MobileJourneyGeocoder:
    def __init__(
        self,
        *,
        settings: MobileSettings,
        cache: Any,
        admission: Any,
        client: httpx.AsyncClient,
    ) -> None:
        self.settings, self.cache, self.admission, self.client = settings, cache, admission, client

    async def _cached(self, key: str) -> MobileJourneyDestinationResponse | None:
        raw = await self.cache.get(key)
        if not raw:
            return None
        try:
            return MobileJourneyDestinationResponse.model_validate_json(raw)
        except (ValidationError, ValueError, TypeError):
            return None

    async def resolve(self, destination: str | None) -> MobileJourneyDestinationResponse:
        query = _query(destination)
        if query is None:
            return MobileJourneyDestinationResponse(status="not_found")
        url = self.settings.journey_geocoding_url
        if url is None:
            return MobileJourneyDestinationResponse(status="not_configured")
        digest = hashlib.sha256(f"{url}\0{_words(query)}".encode()).hexdigest()
        cache_key = f"mobile-journey:photon:v1:{digest}"
        unavailable = MobileJourneyDestinationResponse(status="unavailable", retry_after_seconds=5)
        try:
            cached = await self._cached(cache_key)
            if cached is not None:
                return cached
            token = secrets.token_hex(16)
            # The whole HTTP exchange is bounded by this timeout, with a lease
            # longer than the exchange and a full second after completion.
            admitted = await self.admission.set(
                _PROVIDER_LEASE_KEY,
                token,
                nx=True,
                px=math.ceil(self.settings.journey_geocoding_timeout_seconds * 1_000) + 2_000,
            )
            if not admitted:
                return await self._cached(cache_key) or unavailable
        except (RedisError, OSError, TimeoutError):
            return unavailable
        cooldown_ms = 1_100
        try:
            cached = await self._cached(cache_key)
            if cached is not None:
                return cached
            try:
                async with asyncio.timeout(self.settings.journey_geocoding_timeout_seconds):
                    async with self.client.stream(
                        "GET",
                        url,
                        params=httpx.QueryParams(tuple(_search_params(query))),
                        headers={"User-Agent": self.settings.journey_geocoding_user_agent},
                        follow_redirects=False,
                    ) as response:
                        if response.status_code in {429, 503}:
                            retry = response.headers.get("Retry-After", "300")
                            cooldown_ms = (
                                min(86_400, max(60, int(retry) if retry.isdigit() else 300)) * 1_000
                            )
                        response.raise_for_status()
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            body.extend(chunk)
                            if len(body) > _MAX_RESPONSE_BYTES:
                                raise ValueError("Geocoding response exceeds byte limit")
                        result = select_destination(json.loads(body), query)
            except (httpx.HTTPError, TimeoutError, ValueError, UnicodeError, RecursionError):
                result = MobileJourneyDestinationResponse(status="unavailable")
            ttl = (
                self.settings.journey_geocoding_cache_ttl_seconds
                if result.status == "resolved"
                else self.settings.journey_geocoding_failure_ttl_seconds
            )
            if result.status == "unavailable":
                result.retry_after_seconds = max(ttl, math.ceil(cooldown_ms / 1_000))
            await self.cache.set(cache_key, result.model_dump_json(), ex=ttl)
            return result
        except (RedisError, OSError, TimeoutError):
            return unavailable
        finally:
            try:
                await self.admission.eval(_COOLDOWN, 1, _PROVIDER_LEASE_KEY, token, cooldown_ms)
            except (RedisError, OSError, TimeoutError):
                pass  # Keep the original lease; never bypass admission locally.


async def get_mobile_journey_geocoder() -> AsyncIterator[MobileJourneyGeocoder]:
    settings = get_settings()
    async with (
        Redis.from_url(
            settings.redis.cache_url,
            decode_responses=True,
            socket_timeout=1,
            socket_connect_timeout=1,
        ) as cache,
        Redis.from_url(
            settings.redis.security_url,
            decode_responses=True,
            socket_timeout=1,
            socket_connect_timeout=1,
        ) as admission,
        httpx.AsyncClient(timeout=settings.mobile.journey_geocoding_timeout_seconds) as client,
    ):
        yield MobileJourneyGeocoder(
            settings=settings.mobile, cache=cache, admission=admission, client=client
        )
