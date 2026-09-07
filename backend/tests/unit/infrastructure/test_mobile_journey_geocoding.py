from __future__ import annotations

import asyncio
import hashlib
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError
from redis.exceptions import ConnectionError as RedisConnectionError

from app.core.config.settings import MobileSettings
from app.infrastructure.mobile_journey_geocoding import (
    MobileJourneyGeocoder,
    _search_params,
    select_destination,
)


def feature(name="Dubai", country="United Arab Emirates", code="AE", kind="city", **extra):
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [55.29, 25.26]},
        "properties": {
            "name": name,
            "country": country,
            "countrycode": code,
            "type": kind,
            "osm_value": kind,
            **extra,
        },
    }


def payload(*features):
    return {"type": "FeatureCollection", "features": list(features)}


@pytest.mark.parametrize(
    "query,place,kind",
    [
        ("Australia", feature("Australia", "Australia", "AU", "country"), "country"),
        ("Kerala", feature("Kerala", "India", "IN", "state"), "state"),
        ("Bali, Indonesia", feature("Bali", "Indonesia", "ID", "state"), "state"),
        ("Dubai, UAE", feature(), "city"),
        ("Dubai United Arab Emirates", feature(), "city"),
        ("London, UK", feature("London", "United Kingdom", "GB"), "city"),
        ("New York, USA", feature("New York", "United States", "US"), "city"),
        ("Paris, France", feature("Paris", "France", "FR"), "city"),
    ],
)
def test_exact_places_and_country_aliases_preserve_provider_coordinates(query, place, kind):
    result = select_destination(payload(place), query)
    assert result.status == "resolved"
    assert result.destination.place_type == kind
    assert result.destination.latitude == 25.26
    assert result.destination.longitude == 55.29
    assert result.attribution_url == "https://www.openstreetmap.org/copyright"


def test_country_or_state_is_not_replaced_with_same_named_village():
    for name, country, code, kind in [
        ("Australia", "Australia", "AU", "country"),
        ("Kerala", "India", "IN", "state"),
    ]:
        result = select_destination(
            payload(
                feature(name, country, code, kind),
                feature(name, "Another country", "XX", osm_value="village"),
            ),
            name,
        )
        assert result.destination.place_type == kind
        assert result.destination.country_code == code


@pytest.mark.parametrize("locality_kind", ["town", "city"])
@pytest.mark.parametrize("reverse_order", [False, True])
def test_exact_country_wins_over_foreign_locality_homonyms(locality_kind, reverse_order):
    country = feature("Brazil", "Brazil", "BR", "country")
    country["geometry"]["coordinates"] = [-53.2, -10.3333333]
    places = [
        country,
        feature("Brazil", "United States", "US", state="Indiana", osm_value=locality_kind),
        feature("Brazil", "Trinidad and Tobago", "TT", osm_value="village"),
        feature("Brazil", "Uganda", "UG", osm_value="village"),
    ]
    result = select_destination(payload(*(reversed(places) if reverse_order else places)), "Brazil")
    assert result.status == "resolved"
    assert result.destination.country_code == "BR"
    assert result.destination.place_type == "country"
    assert result.destination.latitude == -10.3333333
    assert result.destination.longitude == -53.2


@pytest.mark.parametrize("query", ["Brazil, Indiana, USA", "Brazil, United States"])
@pytest.mark.parametrize("reverse_order", [False, True])
def test_explicit_foreign_locality_qualifiers_override_country_homonym(query, reverse_order):
    city = feature("Brazil", "United States", "US", state="Indiana", osm_value="town")
    city["geometry"]["coordinates"] = [-87.125, 39.524]
    places = [feature("Brazil", "Brazil", "BR", "country"), city]
    result = select_destination(payload(*(reversed(places) if reverse_order else places)), query)
    assert result.status == "resolved"
    assert result.destination.country_code == "US"
    assert result.destination.place_type == "city"
    assert result.destination.latitude == 39.524
    assert result.destination.longitude == -87.125


@pytest.mark.parametrize("reverse_order", [False, True])
def test_country_preference_preserves_competing_state_even_with_city_homonym(reverse_order):
    places = [
        feature("Georgia", "Georgia", "GE", "country"),
        feature("Georgia", "United States", "US", "state"),
        feature("Georgia", "United States", "US", state="Vermont", osm_value="town"),
    ]
    result = select_destination(
        payload(*(reversed(places) if reverse_order else places)), "Georgia"
    )
    assert result.status == "ambiguous"
    assert result.destination is None


@pytest.mark.parametrize("reverse_order", [False, True])
def test_multiple_exact_country_candidates_do_not_choose_first_provider_result(reverse_order):
    places = [
        feature("Congo", "Congo", "CG", "country"),
        feature("Congo", "Democratic Republic of the Congo", "CD", "country"),
    ]
    places[0]["geometry"]["coordinates"] = [15.0, -1.0]
    places[1]["geometry"]["coordinates"] = [23.0, -3.0]
    result = select_destination(payload(*(reversed(places) if reverse_order else places)), "Congo")
    assert result.status == "ambiguous"
    assert result.destination is None


def test_city_state_duplicate_and_city_country_duplicate_choose_appropriate_scope():
    dubai = select_destination(payload(feature(), feature(kind="state")), "Dubai")
    assert dubai.destination.place_type == "city"
    singapore = select_destination(
        payload(
            feature("Singapore", "Singapore", "SG", "country"),
            feature("Singapore", "Singapore", "SG", "city"),
        ),
        "Singapore",
    )
    assert singapore.destination.place_type == "country"


@pytest.mark.parametrize("query", ["Hongkong", "HONGKONG", "Hong Kong", "Hongkong, China"])
def test_hongkong_spelling_resolves_exact_provider_place_without_accepting_similar_names(query):
    result = select_destination(
        payload(
            feature("Hong Kong", "China", "CN", "state"),
            feature("Hong Kong", "China", "CN", "city", state="Hong Kong"),
            feature("Hongkou", "China", "CN", "city", state="Shanghai"),
        ),
        query,
    )
    assert result.status == "resolved"
    assert result.destination.label == "Hong Kong"
    assert result.destination.place_type == "city"
    assert (
        select_destination(payload(feature("Hongkou", "China", "CN")), query).status == "not_found"
    )


def test_ambiguous_places_and_multistop_never_get_a_guessed_coordinate():
    georgia = select_destination(
        payload(
            feature("Georgia", "Georgia", "GE", "country"),
            feature("Georgia", "United States", "US", "state"),
        ),
        "Georgia",
    )
    assert georgia.status == "ambiguous" and georgia.destination is None
    paris = select_destination(
        payload(
            feature("Paris", "France", "FR"),
            feature("Paris", "United States", "US"),
        ),
        "Paris",
    )
    assert paris.status == "ambiguous" and paris.destination is None
    trip = select_destination(
        payload(feature(), feature("Singapore", "Singapore", "SG")), "Dubai, Singapore"
    )
    assert trip.status != "resolved" and trip.destination is None


@pytest.mark.parametrize(
    "change",
    [
        {"type": []},
        {"type": {}},
        {"name": None},
        {"countrycode": "INVALID"},
    ],
)
def test_malformed_feature_properties_are_rejected(change):
    assert select_destination(payload(feature(**change)), "Dubai").destination is None


@pytest.mark.parametrize(
    "coordinates", [[float("nan"), 0], [0, float("inf")], [181, 0], [0, -91], [True, 1], [0]]
)
def test_invalid_coordinates_never_escape(coordinates):
    place = feature()
    place["geometry"]["coordinates"] = coordinates
    assert select_destination(payload(place), "Dubai").destination is None


def test_fuzzy_venue_and_incomplete_place_matches_are_rejected():
    assert select_destination(payload(feature(name="Dubail")), "Dubai").status == "not_found"
    assert select_destination(payload(feature(kind="house")), "Dubai").status == "not_found"
    assert select_destination(payload(feature()), "Dubai, France").status == "not_found"
    assert select_destination({"features": {}}, "Dubai").status == "unavailable"


class Cache:
    def __init__(self):
        self.values = {}
        self.ttls = {}

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, *, ex):
        self.values[key], self.ttls[key] = value, ex


def admission():
    result = AsyncMock()
    result.set.return_value = True
    return result


async def test_country_resolution_ignores_old_ambiguous_cache_but_keeps_shared_upstream_lease():
    calls, cache, gate = [], Cache(), admission()
    settings = MobileSettings(_env_file=None)
    digest = hashlib.sha256(f"{settings.journey_geocoding_url}\0brazil".encode()).hexdigest()
    previous_key = f"mobile-journey:photon:v1:{digest}"
    cache.values[previous_key] = '{"status":"ambiguous"}'

    def handler(request):
        calls.append(request)
        return httpx.Response(
            200,
            json=payload(
                feature("Brazil", "Brazil", "BR", "country"),
                feature("Brazil", "United States", "US", state="Indiana", osm_value="town"),
            ),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = MobileJourneyGeocoder(
            settings=settings, cache=cache, admission=gate, client=client
        )
        for query in ["Brazil", "  BRAZIL  "]:
            result = await service.resolve(query)
            assert result.status == "resolved"
            assert result.destination.country_code == "BR"
    assert len(calls) == 1
    assert cache.values[previous_key] == '{"status":"ambiguous"}'
    assert f"mobile-journey:photon:v2:{digest}" in cache.values
    gate.set.assert_awaited_once()
    assert gate.set.await_args.args[0] == "mobile-journey:photon:upstream:v1"
    assert gate.eval.await_args.args[2] == "mobile-journey:photon:upstream:v1"


async def test_cached_places_are_shared_across_calls_and_aliases_without_upstream_repeats():
    calls, cache, gate = [], Cache(), admission()

    async def handler(request):
        calls.append(request)
        return httpx.Response(200, json=payload(feature()))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = MobileJourneyGeocoder(
            settings=MobileSettings(_env_file=None), cache=cache, admission=gate, client=client
        )
        for query in ["  DUBAI, UAE  ", "Dubai United Arab Emirates", "Dubai AE"]:
            assert (await service.resolve(query)).status == "resolved"
    assert len(calls) == 1
    assert calls[0].url.params["q"] == "dubai"
    assert calls[0].url.params["countrycode"] == "AE"
    assert calls[0].url.params.get_list("layer") == ["country", "state", "city"]
    assert calls[0].headers["User-Agent"] == "GlobalConnects-TripJourney/1.0"
    assert list(cache.ttls.values()) == [2_592_000]
    assert all("dubai" not in key.casefold() for key in cache.values)
    gate.set.assert_awaited_once()
    assert gate.set.await_args.kwargs["nx"] is True
    assert gate.set.await_args.kwargs["px"] == 7_000
    assert gate.eval.await_args.args[-1] == 1_100


async def test_hongkong_spellings_share_canonical_provider_query_and_cached_coordinates():
    calls, cache = [], Cache()

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=payload(feature("Hong Kong", "China", "CN")))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = MobileJourneyGeocoder(
            settings=MobileSettings(_env_file=None),
            cache=cache,
            admission=admission(),
            client=client,
        )
        for query in ["Hongkong", "Hong Kong", "  HONGKONG  "]:
            assert (await service.resolve(query)).destination.label == "Hong Kong"
    assert len(calls) == 1
    assert calls[0].url.params["q"] == "hong kong"


async def test_destination_edits_use_separate_cache_entries_and_restore_only_matching_place():
    calls, cache = [], Cache()
    places = {
        "vietnam": feature("Vietnam", "Vietnam", "VN", "country"),
        "hong kong": feature("Hong Kong", "China", "CN"),
        "United States": feature("United States", "United States", "US", "country"),
    }
    for place, coordinates in zip(
        places.values(),
        [[107.9650855, 15.9266657], [114.1582831, 22.2818333], [-100.445882, 39.7837304]],
    ):
        place["geometry"]["coordinates"] = coordinates

    def handler(request):
        query = request.url.params["q"]
        calls.append(query)
        return httpx.Response(200, json=payload(places[query]))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = MobileJourneyGeocoder(
            settings=MobileSettings(_env_file=None),
            cache=cache,
            admission=admission(),
            client=client,
        )
        results = [
            await service.resolve(query) for query in ["Vietnam", "Hongkong", "USA", "Vietnam"]
        ]
    assert all(result.status == "resolved" for result in results)
    assert [result.destination.label for result in results] == [
        "Vietnam",
        "Hong Kong",
        "United States",
        "Vietnam",
    ]
    assert [result.destination.longitude for result in results] == [
        107.9650855,
        114.1582831,
        -100.445882,
        107.9650855,
    ]
    assert calls == ["vietnam", "hong kong", "United States"]
    assert len(cache.values) == 3


@pytest.mark.parametrize("mode", ["cache_down", "gate_down", "busy"])
async def test_no_provider_request_without_shared_cache_and_admission(mode):
    cache, gate, calls = Cache(), admission(), []
    if mode == "cache_down":
        cache.get = AsyncMock(side_effect=RedisConnectionError())
    elif mode == "gate_down":
        gate.set.side_effect = RedisConnectionError()
    else:
        gate.set.return_value = None

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=payload(feature()))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await MobileJourneyGeocoder(
            settings=MobileSettings(_env_file=None), cache=cache, admission=gate, client=client
        ).resolve("Dubai")
    assert result.status == "unavailable" and result.destination is None
    assert calls == []


@pytest.mark.parametrize(
    "status,headers,body",
    [
        (429, {"Retry-After": "600"}, b""),
        (302, {"Location": "https://other.example/"}, b""),
        (200, {}, b"not json"),
        (200, {}, b"x" * 131_073),
    ],
    ids=["rate-limit", "redirect", "invalid-json", "oversized-body"],
)
async def test_failures_are_cached_without_redirects_or_immediate_retries(status, headers, body):
    cache, gate, calls = Cache(), admission(), []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, headers=headers, content=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = MobileJourneyGeocoder(
            settings=MobileSettings(_env_file=None), cache=cache, admission=gate, client=client
        )
        first, second = await service.resolve("Dubai"), await service.resolve("Dubai")
    assert first == second and first.status == "unavailable" and first.destination is None
    assert len(calls) == 1 and list(cache.ttls.values()) == [300]
    assert gate.eval.await_args.args[-1] == (600_000 if status == 429 else 1_100)


async def test_request_has_total_deadline_and_releases_admission_to_cooldown():
    cache, gate = Cache(), admission()

    async def handler(request):
        await asyncio.sleep(5)
        return httpx.Response(200, json=payload(feature()))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        settings = MobileSettings(_env_file=None, journey_geocoding_timeout_seconds=1)
        async with asyncio.timeout(2):
            result = await MobileJourneyGeocoder(
                settings=settings, cache=cache, admission=gate, client=client
            ).resolve("Dubai")
    assert result.status == "unavailable" and result.retry_after_seconds == 300
    assert gate.eval.await_args.args[-1] == 1_100


async def test_separate_resolvers_cannot_send_concurrently_and_keep_cooldown():
    class SharedAdmission:
        held = False

        async def set(self, key, token, **options):
            if self.held:
                return None
            self.held = True
            return True

        async def eval(self, script, keys, key, token, ttl):
            # Redis retains the lease during its cooldown instead of deleting it.
            assert ttl >= 1_000

    entered, finish, calls = asyncio.Event(), asyncio.Event(), []

    async def handler(request):
        calls.append(request)
        entered.set()
        await finish.wait()
        return httpx.Response(200, json=payload(feature()))

    cache, gate = Cache(), SharedAdmission()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        settings = MobileSettings(_env_file=None)
        one = MobileJourneyGeocoder(settings=settings, cache=cache, admission=gate, client=client)
        two = MobileJourneyGeocoder(settings=settings, cache=cache, admission=gate, client=client)
        first = asyncio.create_task(one.resolve("Dubai"))
        await entered.wait()
        try:
            assert (await two.resolve("Kerala")).status == "unavailable"
            finish.set()
            assert (await first).status == "resolved"
            assert (await two.resolve("Kerala")).status == "unavailable"
            assert (await two.resolve("Dubai")).status == "resolved"
        finally:
            finish.set()
            await first
    assert len(calls) == 1


@pytest.mark.parametrize("query", [None, "", "user@example.com", "+919999999999", "https://x.test"])
async def test_invalid_destination_never_reaches_external_service(query):
    cache, gate = AsyncMock(), admission()
    async with httpx.AsyncClient() as client:
        result = await MobileJourneyGeocoder(
            settings=MobileSettings(_env_file=None), cache=cache, admission=gate, client=client
        ).resolve(query)
    assert result.status == "not_found"
    cache.get.assert_not_awaited()
    gate.set.assert_not_awaited()


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/api/",
        "https://user:pass@example.com/",
        "https://example.com/?q=x",
        "https://example.com/#x",
    ],
)
def test_settings_allow_only_an_explicit_https_endpoint(url):
    with pytest.raises(ValidationError):
        MobileSettings(_env_file=None, journey_geocoding_url=url)


def test_provider_can_be_switched_or_disabled_and_aliases_use_hard_country_filter():
    assert MobileSettings(_env_file=None, journey_geocoding_url="").journey_geocoding_url is None
    assert MobileSettings(_env_file=None, journey_geocoding_url="https://geo.example/api/")
    assert ("countrycode", "GB") in _search_params("London, UK")
    assert ("q", "United States") in _search_params("USA")
    assert [value for key, value in _search_params("USA") if key == "layer"] == ["country"]
