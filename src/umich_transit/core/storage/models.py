"""SQLAlchemy ORM models. Seven tables: routes, stops, route_stops,
predictions (high-volume), arrivals, reliability_stats (derived), parse_errors."""
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
)
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


class TZDateTime(TypeDecorator[datetime]):
    """DateTime that always returns timezone-aware UTC datetimes.

    SQLite stores datetimes as strings and discards tzinfo on read.
    This decorator re-attaches UTC when the value comes back naive.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Dialect) -> datetime | None:
        dt: datetime | None = value
        if dt is not None and dt.tzinfo is not None:
            return dt.astimezone(UTC)
        return dt

    def process_result_value(self, value: Any, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if not isinstance(value, datetime):
            raise TypeError(f"Expected datetime, got {type(value)!r}")
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


class Base(DeclarativeBase):
    pass


class Route(Base):
    __tablename__ = "routes"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    agency: Mapped[str] = mapped_column(String, nullable=False)  # "mbus" | "theride"
    short_name: Mapped[str] = mapped_column(String, nullable=False)
    long_name: Mapped[str] = mapped_column(String, nullable=False)
    color: Mapped[str | None] = mapped_column(String, nullable=True)
    raw_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(TZDateTime)


class Stop(Base):
    __tablename__ = "stops"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    agency: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)
    raw_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(TZDateTime)


class RouteStop(Base):
    __tablename__ = "route_stops"
    route_id: Mapped[str] = mapped_column(ForeignKey("routes.id"))
    stop_id: Mapped[str] = mapped_column(ForeignKey("stops.id"))
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    __table_args__ = (
        PrimaryKeyConstraint("route_id", "stop_id", "sequence"),
    )


class Prediction(Base):
    __tablename__ = "predictions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    route_id: Mapped[str] = mapped_column(ForeignKey("routes.id"), nullable=False)
    stop_id: Mapped[str] = mapped_column(ForeignKey("stops.id"), nullable=False)
    vehicle_id: Mapped[str] = mapped_column(String, nullable=False)
    predicted_arrival_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    __table_args__ = (
        Index("ix_predictions_stop_route_captured", "stop_id", "route_id", "captured_at"),
        Index("ix_predictions_vehicle_captured", "vehicle_id", "captured_at"),
    )


class Arrival(Base):
    __tablename__ = "arrivals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    route_id: Mapped[str] = mapped_column(ForeignKey("routes.id"), nullable=False)
    stop_id: Mapped[str] = mapped_column(ForeignKey("stops.id"), nullable=False)
    vehicle_id: Mapped[str] = mapped_column(String, nullable=False)
    actual_arrival_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    detected_via: Mapped[str] = mapped_column(String, nullable=False)  # "proximity" | "collapse"
    __table_args__ = (
        Index("ix_arrivals_vehicle_at", "vehicle_id", "actual_arrival_at"),
        Index("ix_arrivals_route_stop_at", "route_id", "stop_id", "actual_arrival_at"),
    )


class ReliabilityStat(Base):
    __tablename__ = "reliability_stats"
    route_id: Mapped[str] = mapped_column(ForeignKey("routes.id"))
    stop_id: Mapped[str] = mapped_column(ForeignKey("stops.id"))
    dow: Mapped[int] = mapped_column(Integer, nullable=False)   # 0=Mon..6=Sun
    hour: Mapped[int] = mapped_column(Integer, nullable=False)  # 0..23
    on_time_pct: Mapped[float] = mapped_column(Float, nullable=False)
    mean_delay_s: Mapped[float] = mapped_column(Float, nullable=False)
    p50_delay_s: Mapped[float] = mapped_column(Float, nullable=False)
    p90_delay_s: Mapped[float] = mapped_column(Float, nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    __table_args__ = (
        PrimaryKeyConstraint("route_id", "stop_id", "dow", "hour"),
    )


class ParseError(Base):
    """Rows that failed to parse from upstream payloads. Audit trail."""
    __tablename__ = "parse_errors"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String, nullable=False)  # "mbus.etas" etc
    occurred_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    error: Mapped[str] = mapped_column(String, nullable=False)
    raw: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
