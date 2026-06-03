"""Typed transit-data records, agency-agnostic.

Clients (mbus, theride, ...) all return these types so downstream code never
sees an upstream-specific payload.
"""
from datetime import datetime

from pydantic import BaseModel


class RouteRecord(BaseModel):
    id: str
    agency: str
    short_name: str
    long_name: str
    color: str | None = None
    raw: dict[str, object]


class StopRecord(BaseModel):
    id: str
    agency: str
    name: str
    lat: float
    lon: float
    raw: dict[str, object]


class VehicleRecord(BaseModel):
    id: str
    route_id: str
    lat: float
    lon: float
    heading: float | None = None
    captured_at: datetime


class EtaRecord(BaseModel):
    route_id: str
    stop_id: str
    vehicle_id: str
    predicted_arrival_at: datetime
    captured_at: datetime
