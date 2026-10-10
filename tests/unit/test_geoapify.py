"""Place search and map tiles through Geoapify.

Two things matter here beyond "does it parse": the API key must never leak to a caller, and a
failed lookup must say *why* so the operator can act (wrong key vs offline vs genuinely no results).
"""
from __future__ import annotations

import asyncio

import httpx
import pytest

from app.environment.external_data.geoapify import (
    GeoapifyPlaceDirectory,
    TileProxy,
    haversine_km,
    parse_features,
)

KEY = "test-key-0000"

AUTOCOMPLETE = {"features": [
    {"type": "Feature", "geometry": {"type": "Point", "coordinates": [74.8016, 12.8406]},
     "properties": {"name": "Tannirbhavi Beach", "lat": 12.8406, "lon": 74.8016,
                    "formatted": "Tannirbhavi Beach, Mangaluru, Karnataka 575001, India",
                    "place_id": "p1", "distance": 1200}},
    {"type": "Feature", "geometry": {"type": "Point", "coordinates": [74.8, 12.93]},
     "properties": {"name": "Panambur Beach", "lat": 12.93, "lon": 74.80,
                    "formatted": "Panambur Beach, Mangaluru, Karnataka, India",
                    "place_id": "p2", "distance": 10300}},
]}


def directory(handler, key: str | None = KEY):
    return GeoapifyPlaceDirectory(key, transport=httpx.MockTransport(handler))


def ok(payload):
    return lambda req: httpx.Response(200, json=payload)


# ---- parsing -------------------------------------------------------------------
def test_parsing_keeps_the_full_address_not_just_a_name():
    """The operator confirms they picked the right place by reading the address."""
    places = parse_features(AUTOCOMPLETE, near=(12.84, 74.80))
    assert places[0].name == "Tannirbhavi Beach"
    assert places[0].address.startswith("Tannirbhavi Beach, Mangaluru, Karnataka")
    assert places[0].label == places[0].address
    assert places[0].source_id == "p1"


def test_distance_comes_from_the_provider_and_sorts_nearest_first():
    places = parse_features(AUTOCOMPLETE, near=(12.84, 74.80))
    assert [p.distance_km for p in places] == [1.2, 10.3]
    assert places[0].name == "Tannirbhavi Beach"


def test_distance_is_computed_when_the_provider_omits_it():
    payload = {"features": [{"properties": {"name": "X", "lat": 12.93, "lon": 74.80}}]}
    [p] = parse_features(payload, near=(12.8406, 74.8016))
    assert p.distance_km == pytest.approx(round(haversine_km(12.8406, 74.8016, 12.93, 74.80), 2))


def test_coordinates_fall_back_to_the_geometry():
    payload = {"features": [{"geometry": {"coordinates": [74.5, 12.5]}, "properties": {"name": "Y"}}]}
    [p] = parse_features(payload)
    assert (p.lat, p.lon) == (12.5, 74.5)


def test_features_without_a_position_are_dropped():
    payload = {"features": [{"properties": {"name": "nowhere"}}, *AUTOCOMPLETE["features"]]}
    assert len(parse_features(payload)) == 2


def test_duplicates_are_collapsed_by_place_id():
    payload = {"features": AUTOCOMPLETE["features"] + AUTOCOMPLETE["features"]}
    assert len(parse_features(payload)) == 2


def test_an_unnamed_place_still_gets_a_label():
    payload = {"features": [{"properties": {"lat": 1, "lon": 2, "formatted": "Some road, Town"}}]}
    [p] = parse_features(payload)
    assert p.name == "Some road, Town" and p.address == "Some road, Town"


# ---- search --------------------------------------------------------------------
def test_search_sends_the_key_and_returns_places():
    seen = {}

    def handler(req):
        seen["url"] = str(req.url)
        return httpx.Response(200, json=AUTOCOMPLETE)

    places = asyncio.run(directory(handler).search("tannirbhavi"))
    assert len(places) == 2
    assert f"apiKey={KEY}" in seen["url"] and "text=tannirbhavi" in seen["url"]


def test_search_biases_to_a_point_when_given_one():
    seen = {}

    def handler(req):
        seen["url"] = str(req.url)
        return httpx.Response(200, json=AUTOCOMPLETE)

    asyncio.run(directory(handler).search("beach", near=(12.84, 74.80)))
    assert "bias=proximity%3A74.8%2C12.84" in seen["url"] or "bias=proximity:74.8,12.84" in seen["url"]


def test_a_one_character_query_never_reaches_the_network():
    calls = []
    d = directory(lambda req: calls.append(1) or httpx.Response(200, json=AUTOCOMPLETE))
    assert asyncio.run(d.search("a")) == []
    assert calls == []


def test_results_are_cached():
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(200, json=AUTOCOMPLETE)

    d = directory(handler)
    asyncio.run(d.search("panambur"))
    asyncio.run(d.search("panambur"))
    assert len(calls) == 1


def test_nearby_beaches_asks_for_the_beach_category_in_a_circle():
    seen = {}

    def handler(req):
        seen["url"] = str(req.url)
        return httpx.Response(200, json=AUTOCOMPLETE)

    asyncio.run(directory(handler).nearby_beaches(12.84, 74.80, 25))
    url = seen["url"]
    assert "categories=beach" in url
    assert "circle%3A74.8%2C12.84%2C25000" in url or "circle:74.8,12.84,25000" in url


def test_the_radius_is_clamped_to_something_the_api_accepts():
    seen = {}

    def handler(req):
        seen["url"] = str(req.url)
        return httpx.Response(200, json={"features": []})

    asyncio.run(directory(handler).nearby_beaches(0, 0, 9999))
    assert "50000" in seen["url"]


# ---- failure reporting ----------------------------------------------------------
def test_a_rejected_key_says_so_rather_than_returning_no_results():
    d = directory(lambda req: httpx.Response(401))
    assert asyncio.run(d.search("anything")) == []
    assert "key" in d.last_error.lower() and "401" in d.last_error


def test_being_offline_says_so():
    def handler(req):
        raise httpx.ConnectError("no network")

    d = directory(handler)
    assert asyncio.run(d.search("anything")) == []
    assert "unreachable" in d.last_error


def test_a_successful_lookup_clears_the_previous_error():
    responses = [httpx.Response(503), httpx.Response(200, json=AUTOCOMPLETE)]
    d = directory(lambda req: responses.pop(0))
    asyncio.run(d.search("first"))
    assert d.last_error
    asyncio.run(d.search("second"))
    assert d.last_error is None


def test_with_no_key_it_reports_unavailable_and_never_calls_out():
    calls = []
    d = directory(lambda req: calls.append(1) or httpx.Response(200, json=AUTOCOMPLETE), key=None)
    assert d.available is False
    assert asyncio.run(d.search("panambur")) == []
    assert calls == [] and "no Geoapify API key" in d.last_error


# ---- tile proxy -----------------------------------------------------------------
def test_tiles_are_fetched_with_the_key_and_cached():
    calls = []

    def handler(req):
        calls.append(str(req.url))
        return httpx.Response(200, content=b"PNGDATA")

    proxy = TileProxy(KEY, transport=httpx.MockTransport(handler))
    assert asyncio.run(proxy.tile(14, 11, 7)) == b"PNGDATA"
    assert asyncio.run(proxy.tile(14, 11, 7)) == b"PNGDATA"
    assert len(calls) == 1, "a tile for a given z/x/y never changes"
    assert f"apiKey={KEY}" in calls[0] and "/14/11/7.png" in calls[0]


def test_the_style_is_part_of_the_cache_key():
    calls = []
    proxy = TileProxy(KEY, transport=httpx.MockTransport(
        lambda req: calls.append(str(req.url)) or httpx.Response(200, content=b"X")))
    asyncio.run(proxy.tile(1, 1, 1, style="positron"))
    asyncio.run(proxy.tile(1, 1, 1, style="dark-matter"))
    assert len(calls) == 2 and "positron" in calls[0] and "dark-matter" in calls[1]


def test_a_retina_tile_asks_for_the_2x_image():
    calls = []
    proxy = TileProxy(KEY, transport=httpx.MockTransport(
        lambda req: calls.append(str(req.url)) or httpx.Response(200, content=b"X")))
    asyncio.run(proxy.tile(5, 2, 3, retina=True))
    assert "3@2x.png" in calls[0]


def test_an_unreachable_tile_server_returns_none_rather_than_raising():
    def handler(req):
        raise httpx.ConnectError("down")

    assert asyncio.run(TileProxy(KEY, transport=httpx.MockTransport(handler)).tile(1, 1, 1)) is None


def test_without_a_key_the_proxy_is_unavailable_and_fetches_nothing():
    calls = []
    proxy = TileProxy(None, transport=httpx.MockTransport(
        lambda req: calls.append(1) or httpx.Response(200, content=b"X")))
    assert proxy.available is False
    assert asyncio.run(proxy.tile(1, 1, 1)) is None and calls == []


def test_the_tile_cache_is_bounded():
    """A long session panning a map must not grow memory without limit."""
    proxy = TileProxy(KEY, cache_entries=4, transport=httpx.MockTransport(
        lambda req: httpx.Response(200, content=b"X")))
    for i in range(20):
        asyncio.run(proxy.tile(10, i, i))
    assert len(proxy._cache._d) <= 4
