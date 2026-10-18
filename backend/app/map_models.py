"""Validated optional metadata. Coordinates never imply a verified platform."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    kind: Literal['platform', 'train']
    station_id: str | None = Field(default=None, max_length=100)
    station_name: str | None = Field(default=None, max_length=100)
    platform_label: str | None = Field(default=None, max_length=100)
    direction: str | None = Field(default=None, max_length=100)
    line: str | None = Field(default=None, max_length=100)
    coordinates: Coordinates | None = None
    source: Literal['configured', 'telemetry', 'estimated', 'simulated'] = 'configured'
    meeting_point: MeetingPoint | None = None
    train_id: str | None = Field(default=None, max_length=100)
    car_id: str | None = Field(default=None, max_length=100)

    @model_validator(mode='after')
    def require_train(self):
        if self.kind == 'train' and not self.train_id:
            raise ValueError('train cameras require train_id')
        return self
