"""Map tile proxy.

Leaflet needs a tile URL the browser can fetch, and Geoapify authenticates with a key in that URL.
Putting the key there would publish it to anyone who opens the Control Room. So the browser asks
*this* application for tiles, and the application fetches them with the key.

Tiles for a given z/x/y never change, so they are cached in memory and served with a long
``Cache-Control``; after the first pan the browser stops asking at all.

WHY THIS ROUTE IS UNAUTHENTICATED
---------------------------------
Leaflet requests tiles as plain ``<img src=...>`` elements. An image request carries no custom
headers, so it cannot present the ``X-Dev-Role``/bearer credential every other API route requires:
a role-guarded tile route answers 401 to its only caller and the map renders blank. Query-string
credentials are deliberately refused on HTTP (see app.security.dependencies), so they are not an
option either.

What the proxy protects is the *key*, not the imagery. The key stays server-side whether or not
this route checks a role, and the tiles themselves are public OpenStreetMap-derived raster images
served like any other static asset under /ui. The residual exposure is upstream quota: anyone who
can reach this host can request tiles through it. That is accepted for a single-beach LAN
deployment. If the installation is ever exposed beyond the operator network, replace this with a
short-lived signed tile token minted by an authenticated endpoint and verified here - do not
re-add require_roles, which only restores the 401.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from fastapi.responses import Response

from app.shared.dependencies import get_container

router = APIRouter(prefix="/map", tags=["map"])

STYLE_PATTERN = r"^[a-z0-9\-]{3,40}$"
MAX_ZOOM = 22
#: Tiles are immutable; a day in the browser cache saves thousands of requests during a demo.
TILE_CACHE_CONTROL = "public, max-age=86400, immutable"
#: A 1x1 transparent PNG, served when a tile cannot be fetched so Leaflet shows a gap, not an error.
BLANK_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000a49444154"
    "789c63000100000500010d0a2db40000000049454e44ae426082"
)


@router.get("/tiles/{style}/{z}/{x}/{y}.png", include_in_schema=False)
async def map_tile(
    style: Annotated[str, Path(pattern=STYLE_PATTERN)],
    z: Annotated[int, Path(ge=0, le=MAX_ZOOM)],
    x: Annotated[int, Path(ge=0)],
    y: Annotated[int, Path(ge=0)],
    retina: Annotated[bool, Query()] = False,
    container=Depends(get_container),
):
    """One map tile, fetched with the server's key.

    Returns a transparent tile rather than an error when the upstream is unreachable: a map with a
    few missing squares is usable, a map that throws is not.
    """
    data = await container.tile_proxy.tile(z, x, y, style=style, retina=retina)
    if data is None:
        return Response(BLANK_PNG, media_type="image/png",
                        headers={"Cache-Control": "no-store"})  # retry next time
    return Response(data, media_type="image/png", headers={"Cache-Control": TILE_CACHE_CONTROL})
