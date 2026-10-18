"""Validated optional metadata. Coordinates never imply a verified platform."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class Coordinates(BaseModel):
    model_config = ConfigDict(extra='forbid')
    lat: float = Field(ge=-90, le=90, allow_inf_nan=False)
    lon: float = Field(ge=-180, le=180, allow_inf_nan=False)
    precision: Literal['station_centroid', 'verified_platform', 'verified_meeting_point', 'approximate']


class MeetingPoint(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    verified: Literal[True]
    coordinates: Coordinates | None = None


class LocationMetadata(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['platform'] = 'platform'
    station_id: str | None = Field(default=None, max_length=100)
    station_name: str | None = Field(default=None, max_length=100)
    platform_label: str | None = Field(default=None, max_length=100)
    direction: str | None = Field(default=None, max_length=100)
    line: str | None = Field(default=None, max_length=100)
    coordinates: Coordinates | None = None
    source: Literal['configured', 'estimated'] = 'configured'
    meeting_point: MeetingPoint | None = None
