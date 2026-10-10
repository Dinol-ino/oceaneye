from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query

from app.camera.services.camera_service import CameraService
from app.core.domain.value_objects import Polygon
from app.core.enums import Role
from app.core.exceptions import NotFoundError
from app.environment.api.schemas import (
    BeachSiteCreate,
    BeachSiteOut,
    BeachSiteUpdate,
    PlaceOut,
    PlaceSearchResponse,
    WeatherResponse,
    ZoneResponse,
    ZoneUpdate,
)
from app.environment.beaches.service import BeachService, NewBeachCommand
from app.environment.external_data.base import EnvironmentalDataProvider
from app.environment.zones.service import ZoneService
from app.security.authorization import ADMIN_ROLES, HUMAN_ROLES, MANAGEMENT_ROLES
from app.security.dependencies import require_roles
from app.security.validation import SAFE_ID_PATTERN
from app.shared.dependencies import get_beach_service, get_camera_service, get_env_provider, get_zone_service

router = APIRouter(tags=["environment"])
CameraId = Annotated[str, Path(pattern=SAFE_ID_PATTERN)]
BeachId = Annotated[str, Path(pattern=SAFE_ID_PATTERN)]
Lat = Annotated[float, Query(ge=-90, le=90)]
Lon = Annotated[float, Query(ge=-180, le=180)]
OptLat = Annotated[float | None, Query(ge=-90, le=90)]
OptLon = Annotated[float | None, Query(ge=-180, le=180)]


# ---- danger zones -----------------------------------------------------------------
@router.get("/zones/{camera_id}", response_model=ZoneResponse,
            dependencies=[Depends(require_roles(*HUMAN_ROLES, Role.SERVICE))])
async def get_zone(camera_id: CameraId, cameras: CameraService = Depends(get_camera_service),
                   zones: ZoneService = Depends(get_zone_service)):
    cameras.get(camera_id)  # 404 if camera unknown
    zone = zones.get_zone(camera_id)
    if zone is None:
        raise NotFoundError("Zone for camera", camera_id)
    return ZoneResponse.from_domain(zone)


@router.put("/zones/{camera_id}", response_model=ZoneResponse, dependencies=[Depends(require_roles(*MANAGEMENT_ROLES))])
async def set_zone(camera_id: CameraId, body: ZoneUpdate, cameras: CameraService = Depends(get_camera_service),
                   zones: ZoneService = Depends(get_zone_service)):
    """Manually configured static danger-zone polygon (normalised coordinates)."""
    cameras.get(camera_id)
    return ZoneResponse.from_domain(zones.set_static_zone(camera_id, Polygon(tuple(map(tuple, body.polygon))), body.name))


# ---- finding a place --------------------------------------------------------------
@router.get("/places/search", response_model=PlaceSearchResponse,
            dependencies=[Depends(require_roles(*HUMAN_ROLES))])
async def search_places(q: Annotated[str, Query(min_length=2, max_length=120)],
                        lat: OptLat = None, lon: OptLon = None,
                        limit: Annotated[int, Query(ge=1, le=20)] = 10,
                        beaches: BeachService = Depends(get_beach_service)):
    """Free-text place search: a beach, a town, a district - anything the operator types.

    Always 200. When the lookup is unavailable the list is empty and ``error`` says why, so the
    interface can tell the operator to type the place in by hand instead of showing "no results".
    """
    results = await beaches.search(q, near=(lat, lon) if lat is not None and lon is not None else None,
                                   limit=limit)
    return PlaceSearchResponse(query=q, results=[PlaceOut.from_domain(p) for p in results],
                               available=beaches.search_available, error=beaches.search_error)


@router.get("/places/beaches-near", response_model=PlaceSearchResponse,
            dependencies=[Depends(require_roles(*HUMAN_ROLES))])
async def beaches_near(lat: Lat, lon: Lon,
                       radius_km: Annotated[float, Query(gt=0, le=50)] = 25,
                       beaches: BeachService = Depends(get_beach_service)):
    """Beaches around a point. Used by the setup picker and by the dashboard map."""
    results = await beaches.nearby_beaches(lat, lon, radius_km)
    return PlaceSearchResponse(query=f"beaches within {radius_km:g} km",
                               results=[PlaceOut.from_domain(p) for p in results],
                               available=beaches.search_available, error=beaches.search_error)


# ---- the deployment site ------------------------------------------------------------
@router.get("/beaches", response_model=list[BeachSiteOut], dependencies=[Depends(require_roles(*HUMAN_ROLES))])
async def list_beach_sites(beaches: BeachService = Depends(get_beach_service)):
    """Configured sites, the active deployment first."""
    return [BeachSiteOut.from_domain(b, beaches.camera_count(b.id)) for b in beaches.list()]


@router.get("/beaches/active", response_model=BeachSiteOut, dependencies=[Depends(require_roles(*HUMAN_ROLES))])
async def active_beach_site(beaches: BeachService = Depends(get_beach_service)):
    beach = beaches.active()
    if beach is None:
        raise NotFoundError("Active beach", "none configured")
    return BeachSiteOut.from_domain(beach, beaches.camera_count(beach.id))


@router.post("/beaches", response_model=BeachSiteOut, status_code=201,
             dependencies=[Depends(require_roles(*MANAGEMENT_ROLES))])
async def add_beach_site(body: BeachSiteCreate, beaches: BeachService = Depends(get_beach_service)):
    """Configure a beach, from a search result or typed in by hand. Becomes the deployment site
    unless ``activate`` is false."""
    beach = beaches.add(NewBeachCommand(**body.model_dump()))
    return BeachSiteOut.from_domain(beach, beaches.camera_count(beach.id))


@router.patch("/beaches/{beach_id}", response_model=BeachSiteOut,
              dependencies=[Depends(require_roles(*MANAGEMENT_ROLES))])
async def update_beach_site(beach_id: BeachId, body: BeachSiteUpdate,
                            beaches: BeachService = Depends(get_beach_service)):
    beach = beaches.update(beach_id, **body.model_dump(exclude_unset=True))
    return BeachSiteOut.from_domain(beach, beaches.camera_count(beach.id))


@router.post("/beaches/{beach_id}/activate", response_model=BeachSiteOut,
             dependencies=[Depends(require_roles(*ADMIN_ROLES))])
async def activate_beach_site(beach_id: BeachId, beaches: BeachService = Depends(get_beach_service)):
    """Change which beach this installation watches. Administrator-only: it redefines the deployment."""
    beach = beaches.activate(beach_id)
    return BeachSiteOut.from_domain(beach, beaches.camera_count(beach.id))


# ---- sea & weather ------------------------------------------------------------------
@router.get("/weather", response_model=WeatherResponse,
            dependencies=[Depends(require_roles(*HUMAN_ROLES, Role.SERVICE))])
async def get_weather(lat: Lat, lon: Lon, provider: EnvironmentalDataProvider = Depends(get_env_provider)):
    """Cached proxy to Open-Meteo forecast + marine APIs."""
    return WeatherResponse.from_domain(await provider.get_conditions(lat, lon))
