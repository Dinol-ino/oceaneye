"""Geoapify: place search and map tiles from one API key.

Replaces the OpenStreetMap Overpass lookup, which rate-limited constantly and needed a region
bounding box to search at all. Geoapify answers free text ("panambur beach", "Mangaluru", "Goa")
accurately and in one call, so setting up a deployment is a search box rather than a dropdown.

**The key never reaches the browser.** Place search already runs server-side. Map tiles would
normally need the key in a URL the browser fetches, so they are proxied through this application
instead - see :class:`TileProxy`. An unrestricted key pasted into a page is a key anyone who opens
that page can copy.
"""
from __future__ import annotations

import logging
import math
import time
from typing import Any

import httpx

from app.environment.external_data.base import PlaceDirectory, PlaceResult

logger = logging.getLogger(__name__)

PLACES_URL = "https://api.geoapify.com/v2/places"
AUTOCOMPLETE_URL = "https://api.geoapify.com/v1/geocode/autocomplete"
TILE_URL = "https://maps.geoapify.com/v1/tile/{style}/{z}/{x}/{y}.png"
USER_AGENT = "OceanEye-prototype/0.4"
BEACH_CATEGORIES = "beach,natural.water"
#: Geoapify's own attribution requirement, shown on the map.
ATTRIBUTION = 'Powered by <a href="https://www.geoapify.com/">Geoapify</a> | &copy; OpenStreetMap contributors'


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(a))


class _TtlCache:
    def __init__(self, ttl: float, max_entries: int = 512) -> None:
        self.ttl, self._max, self._d = ttl, max_entries, {}

    def get(self, key):
        hit = self._d.get(key)
        return hit[1] if hit and time.monotonic() - hit[0] < self.ttl else None

    def put(self, key, value) -> None:
        if len(self._d) >= self._max:          # cheap bound: drop the oldest entry
            self._d.pop(next(iter(self._d)), None)
        self._d[key] = (time.monotonic(), value)


def parse_features(payload: dict[str, Any], near: tuple[float, float] | None = None) -> list[PlaceResult]:
    """GeoJSON FeatureCollection -> PlaceResults, de-duplicated, nearest first when biased.

    Pure, so the response shape is unit-testable without a key or a network.
    """
    seen: dict[str, PlaceResult] = {}
    for feature in payload.get("features", []):
        p = feature.get("properties") or {}
        lat, lon = p.get("lat"), p.get("lon")
        if lat is None or lon is None:
            coords = (feature.get("geometry") or {}).get("coordinates") or []
            if len(coords) != 2:
                continue
            lon, lat = coords
        name = p.get("name") or p.get("address_line1") or p.get("formatted") or "Unnamed place"
        address = p.get("formatted") or ", ".join(
            x for x in (p.get("address_line1"), p.get("address_line2")) if x) or name
        distance_m = p.get("distance")
        distance_km = (round(distance_m / 1000, 2) if isinstance(distance_m, (int, float))
                       else (round(haversine_km(near[0], near[1], float(lat), float(lon)), 2)
                             if near else None))
        result = PlaceResult(name=str(name), lat=float(lat), lon=float(lon), address=str(address),
                             distance_km=distance_km, source_id=p.get("place_id"))
        key = result.source_id or f"{result.name}|{result.lat:.4f},{result.lon:.4f}"
        if key not in seen:
            seen[key] = result
    out = list(seen.values())
    if near:
        out.sort(key=lambda r: r.distance_km if r.distance_km is not None else 1e9)
    return out


class GeoapifyPlaceDirectory(PlaceDirectory):
    def __init__(self, api_key: str | None, *, ttl_seconds: int = 3600, timeout: float = 15.0,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._key = (api_key or "").strip()
        self._cache = _TtlCache(ttl_seconds)
        self._timeout, self._transport = timeout, transport
        self._last_error: str | None = None if self._key else "no Geoapify API key configured"

    @property
    def available(self) -> bool:
        return bool(self._key)

    @property
    def last_error(self) -> str | None:
        return self._last_error

    async def _get(self, url: str, params: dict[str, Any],
                   near: tuple[float, float] | None) -> list[PlaceResult]:
        if not self._key:
            self._last_error = "no Geoapify API key configured"
            return []
        cache_key = (url, tuple(sorted(params.items())))
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                resp = await client.get(url, params={**params, "apiKey": self._key},
                                        headers={"User-Agent": USER_AGENT})
                resp.raise_for_status()
                results = parse_features(resp.json(), near)
        except httpx.HTTPStatusError as exc:
            # 401 means the key is wrong; say so plainly rather than "no results".
            code = exc.response.status_code
            self._last_error = ("Geoapify rejected the API key (401)" if code == 401
                                else f"Geoapify returned HTTP {code}")
            logger.warning("geoapify request failed: %s", self._last_error)
            return []
        except Exception as exc:  # noqa: BLE001 - offline must not break setup
            self._last_error = f"Geoapify unreachable ({type(exc).__name__})"
            logger.warning("geoapify request failed: %s", self._last_error)
            return []
        self._last_error = None
        self._cache.put(cache_key, results)
        return results

    async def search(self, text: str, *, near: tuple[float, float] | None = None,
                     limit: int = 10) -> list[PlaceResult]:
        text = (text or "").strip()
        if len(text) < 2:
            return []
        params: dict[str, Any] = {"text": text, "limit": max(1, min(limit, 20)), "format": "geojson"}
        if near:
            params["bias"] = f"proximity:{near[1]},{near[0]}"   # Geoapify takes lon,lat
        return await self._get(AUTOCOMPLETE_URL, params, near)

    async def nearby_beaches(self, lat: float, lon: float, radius_km: float,
                             limit: int = 20) -> list[PlaceResult]:
        radius_m = int(max(0.1, min(radius_km, 50)) * 1000)
        params = {
            "categories": BEACH_CATEGORIES,
            "filter": f"circle:{lon},{lat},{radius_m}",
            "bias": f"proximity:{lon},{lat}",
            "limit": max(1, min(limit, 50)),
        }
        return await self._get(PLACES_URL, params, (lat, lon))


class TileProxy:
    """Fetches map tiles from Geoapify so the browser never sees the API key.

    Tiles are immutable for a given z/x/y, so they are cached in memory and served with a long
    ``Cache-Control``; after the first pan the browser stops asking us at all. Without a key this
    reports unavailable and the dashboard shows the map area empty rather than broken.
    """

    def __init__(self, api_key: str | None, *, style: str = "osm-bright-smooth",
                 cache_entries: int = 2000, timeout: float = 10.0,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._key = (api_key or "").strip()
        self.style = style
        self._cache = _TtlCache(ttl=24 * 3600, max_entries=cache_entries)
        self._timeout, self._transport = timeout, transport

    @property
    def available(self) -> bool:
        return bool(self._key)

    async def tile(self, z: int, x: int, y: int, style: str | None = None,
                   retina: bool = False) -> bytes | None:
        """One PNG tile, or None when it cannot be fetched."""
        if not self._key:
            return None
        style = style or self.style
        key = (style, z, x, y, retina)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        url = TILE_URL.format(style=style, z=z, x=x, y=f"{y}@2x" if retina else y)
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                resp = await client.get(url, params={"apiKey": self._key},
                                        headers={"User-Agent": USER_AGENT})
                resp.raise_for_status()
                data = resp.content
        except Exception as exc:  # noqa: BLE001 - a missing tile is a grey square, not an outage
            logger.warning("tile %s/%s/%s/%s failed: %s", style, z, x, y, type(exc).__name__)
            return None
        self._cache.put(key, data)
        return data
