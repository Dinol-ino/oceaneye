from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.domain.geometry import is_normalized
from app.core.entities.beach import Beach
from app.core.entities.zone import Zone
from app.core.enums import ZoneMode
from app.environment.external_data.base import EnvironmentalConditions, PlaceResult


class ZoneResponse(BaseModel):
    id: str
    camera_id: str
    name: str
    mode: ZoneMode
    polygon: list[tuple[float, float]]  # normalised image coordinates (0..1, origin top-left)
    updated_at: datetime

    @classmethod
    def from_domain(cls, z: Zone) -> "ZoneResponse":
        return cls(id=z.id, camera_id=z.camera_id, name=z.name, mode=z.mode,
                   polygon=[tuple(p) for p in z.polygon.points], updated_at=z.updated_at)


class ZoneUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(default="Danger zone", min_length=1, max_length=120)
    polygon: list[tuple[float, float]] = Field(min_length=3, max_length=200)

    @field_validator("polygon")
    @classmethod
    def _normalised(cls, v):
        if not is_normalized(v):
            raise ValueError("polygon points must be normalised to 0..1 (x / width, y / height)")
        return v


class ForecastOut(BaseModel):
    time: str
    wind_speed_ms: float | None = None
    wind_gusts_ms: float | None = None
    wave_height_m: float | None = None
    swell_height_m: float | None = None
    sea_level_m: float | None = None
    precipitation_prob: float | None = None


class WeatherResponse(BaseModel):
    source: str
    status: str
    error: str | None = None
    lat: float
    lon: float
    fetched_at: datetime
    wind_speed_ms: float | None = None
    wind_gusts_ms: float | None = None
    wind_direction_deg: float | None = None
    air_temperature_c: float | None = None
    weather_code: int | None = None
    precipitation_mm: float | None = None
    wave_height_m: float | None = None
    wave_period_s: float | None = None
    wave_direction_deg: float | None = None
    swell_height_m: float | None = None
    tide_height_m: float | None = None
    sea_surface_temperature_c: float | None = None
    ocean_current_ms: float | None = None
    forecast: list[ForecastOut] = []
    note: str | None = None

    @classmethod
    def from_domain(cls, c: EnvironmentalConditions) -> "WeatherResponse":
        data = {k: getattr(c, k) for k in cls.model_fields if k not in ("forecast", "note") and hasattr(c, k)}
        note = "MOCK provider: no real data" if c.source == "mock" else None
        return cls(**data, forecast=[ForecastOut(**p.__dict__) for p in c.forecast], note=note)


class PlaceOut(BaseModel):
    """A place found on the map: a candidate for deployment, not a configured site."""

    name: str
    address: str
    lat: float
    lon: float
    distance_km: float | None = None
    source_id: str | None = None

    @classmethod
    def from_domain(cls, p: PlaceResult) -> "PlaceOut":
        return cls(name=p.name, address=p.address, lat=p.lat, lon=p.lon,
                   distance_km=p.distance_km, source_id=p.source_id)


class PlaceSearchResponse(BaseModel):
    """Results plus why there are none, so the UI can say something useful instead of "0 results"."""

    query: str
    results: list[PlaceOut]
    available: bool          # is place search configured at all?
    error: str | None = None


class BeachSiteOut(BaseModel):
    """A configured deployment site."""

    id: str
    name: str
    region: str
    label: str
    lat: float
    lon: float
    is_active: bool
    authority_name: str | None = None
    authority_phone: str | None = None
    lifeguard_count: int
    notes: str | None = None
    camera_count: int = 0
    created_at: datetime

    @classmethod
    def from_domain(cls, b: Beach, camera_count: int = 0) -> "BeachSiteOut":
        return cls(id=b.id, name=b.name, region=b.region, label=b.label, lat=b.location.lat,
                   lon=b.location.lon, is_active=b.is_active, authority_name=b.authority_name,
                   authority_phone=b.authority_phone, lifeguard_count=b.lifeguard_count, notes=b.notes,
                   camera_count=camera_count, created_at=b.created_at)


class BeachSiteCreate(BaseModel):
    """Either picked from a search result, or typed in by hand when the lookup is unavailable."""

    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=160)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    region: str = Field(default="", max_length=160)  # free text from the map, e.g. "Mangaluru, Karnataka"
    authority_name: str | None = Field(default=None, max_length=160)
    authority_phone: str | None = Field(default=None, max_length=40)
    lifeguard_count: int = Field(default=0, ge=0, le=500)
    notes: str | None = Field(default=None, max_length=1000)
    source_id: str | None = Field(default=None, max_length=120)
    activate: bool = True   # picking a beach during setup almost always means "watch this one"

    #: 0,0 is in the Atlantic off West Africa ("null island"). It is what every uninitialised
    #: coordinate field collapses to, so it is far more likely to be a missing value than a real
    #: site. Accepting it silently produces an installation whose map renders open ocean and whose
    #: weather, tide and nearby-beach lookups all describe the wrong hemisphere - the failure shows
    #: up much later, as "the map is broken", with nothing pointing back to the beach record.
    @model_validator(mode="after")
    def _reject_null_island(self) -> "BeachSiteCreate":
        if self.lat == 0 and self.lon == 0:
            raise ValueError(
                "Latitude and longitude are both 0, which is a point in the Atlantic Ocean rather "
                "than a beach. Pick the site from search, or type its real coordinates."
            )
        return self


class BeachSiteUpdate(BaseModel):
    """Only the details an authority maintains. A beach that moved is a different site."""

    model_config = ConfigDict(extra="forbid")
    authority_name: str | None = Field(default=None, max_length=160)
    authority_phone: str | None = Field(default=None, max_length=40)
    lifeguard_count: int | None = Field(default=None, ge=0, le=500)
    notes: str | None = Field(default=None, max_length=1000)
