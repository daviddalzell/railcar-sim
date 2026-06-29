import os
from datetime import datetime
from typing import List, Optional
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database import Base

_is_sqlite = os.environ.get("DATABASE_URL", "sqlite:///./railcar.db").startswith("sqlite")


class Tenant(Base):
    """Registry of all tenants. Lives in the shared public schema."""
    __tablename__ = "tenants"
    __table_args__ = {} if _is_sqlite else {"schema": "public"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    schema_name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    subscription_status: Mapped[str] = mapped_column(String, default="active")
    subscription_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    gemini_api_key: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    anthropic_api_key: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    openai_api_key: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    vision_provider: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=datetime.utcnow)


class SwitchingArea(Base):
    __tablename__ = "switching_areas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    car_capacity: Mapped[int] = mapped_column(Integer, default=10)

    locations: Mapped[List["Location"]] = relationship("Location", back_populates="switching_area")


class Location(Base):
    __tablename__ = "locations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    location_type: Mapped[str] = mapped_column(String, default="yard")  # yard / industry / staging
    switching_area_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("switching_areas.id"), nullable=True)
    car_capacity: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    switching_area: Mapped[Optional["SwitchingArea"]] = relationship("SwitchingArea", back_populates="locations")
    cars: Mapped[List["Car"]] = relationship("Car", back_populates="current_location")
    industries: Mapped[List["Industry"]] = relationship("Industry", back_populates="location")
    origin_waybills: Mapped[List["Waybill"]] = relationship("Waybill", foreign_keys="Waybill.origin_id", back_populates="origin")
    destination_waybills: Mapped[List["Waybill"]] = relationship("Waybill", foreign_keys="Waybill.destination_id", back_populates="destination")


class Industry(Base):
    __tablename__ = "industries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    location_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("locations.id"), nullable=True)
    accepted_car_types: Mapped[str] = mapped_column(String, default="")
    commodities: Mapped[str] = mapped_column(String, default="")
    industry_role: Mapped[str] = mapped_column(String, default="consumer")
    inbound_car_types: Mapped[str] = mapped_column(String, default="")
    outbound_commodities: Mapped[str] = mapped_column(String, default="")
    outbound_car_types: Mapped[str] = mapped_column(String, default="")
    spot_numbers: Mapped[str] = mapped_column(String, default="")

    location: Mapped[Optional["Location"]] = relationship("Location", back_populates="industries")
    waybills: Mapped[List["Waybill"]] = relationship("Waybill", back_populates="industry")


class Car(Base):
    __tablename__ = "cars"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    car_type: Mapped[str] = mapped_column(String, nullable=False)
    color: Mapped[str] = mapped_column(String, default="")
    car_number: Mapped[str] = mapped_column(String, default="")
    reporting_marks: Mapped[str] = mapped_column(String, default="")
    photo_path: Mapped[str] = mapped_column(String, default="")
    current_location_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("locations.id"), nullable=True)
    active_waybill_slot: Mapped[int] = mapped_column(Integer, default=0)
    cp_session_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    current_location: Mapped[Optional["Location"]] = relationship("Location", back_populates="cars")
    waybills: Mapped[List["Waybill"]] = relationship("Waybill", back_populates="car", order_by="Waybill.slot_index", foreign_keys="Waybill.car_id")
    movement_logs: Mapped[List["MovementLog"]] = relationship("MovementLog", back_populates="car")


class Waybill(Base):
    __tablename__ = "waybills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String, default="")
    car_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("cars.id"), nullable=True)
    slot_index: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    origin_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("locations.id"), nullable=True)
    destination_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("locations.id"), nullable=True)
    industry_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("industries.id"), nullable=True)
    commodity: Mapped[str] = mapped_column(String, default="")
    is_empty: Mapped[bool] = mapped_column(Boolean, default=False)
    required_car_type: Mapped[Optional[str]] = mapped_column(String, nullable=True, default=None)

    car: Mapped[Optional["Car"]] = relationship("Car", back_populates="waybills", foreign_keys=[car_id])
    origin: Mapped[Optional["Location"]] = relationship("Location", foreign_keys=[origin_id], back_populates="origin_waybills")
    destination: Mapped[Optional["Location"]] = relationship("Location", foreign_keys=[destination_id], back_populates="destination_waybills")
    industry: Mapped[Optional["Industry"]] = relationship("Industry", back_populates="waybills")


class MovementLog(Base):
    __tablename__ = "movement_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    car_id: Mapped[int] = mapped_column(Integer, ForeignKey("cars.id"), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    from_location_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("locations.id"), nullable=True)
    to_location_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("locations.id"), nullable=True)
    note: Mapped[str] = mapped_column(String, default="")

    car: Mapped["Car"] = relationship("Car", back_populates="movement_logs")


class CommodityCarTypeMap(Base):
    __tablename__ = "commodity_car_type_map"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    commodity: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    car_type: Mapped[str] = mapped_column(String, nullable=False)


class CarType(Base):
    __tablename__ = "car_types"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    default_photo_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)


class LayoutSettings(Base):
    __tablename__ = "layout_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    clock_start_time: Mapped[str] = mapped_column(String, default="08:00")
    clock_speed: Mapped[int] = mapped_column(Integer, default=4)
    ops_mode: Mapped[str] = mapped_column(String, default="free")  # "free" | "timetable_train_order" | "track_warrant"


class SessionClock(Base):
    __tablename__ = "session_clock"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    started_at: Mapped[Optional[float]] = mapped_column(nullable=True)
    paused_at: Mapped[Optional[float]] = mapped_column(nullable=True)
    paused_accum_s: Mapped[float] = mapped_column(default=0.0)
    start_time: Mapped[str] = mapped_column(String, default="08:00")
    speed: Mapped[int] = mapped_column(Integer, default=4)


class DispatchPlan(Base):
    __tablename__ = "dispatch_plan"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_type: Mapped[str] = mapped_column(String, default="switching")  # "switching" | "transfer" (future)
    origin_location_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("locations.id"), nullable=True)
    switching_area_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("switching_areas.id"), nullable=True)
    destination_location_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("locations.id"), nullable=True)
    setout_ids_json: Mapped[str]           = mapped_column(String, default="[]")
    pickup_ids_json: Mapped[str]           = mapped_column(String, default="[]")
    spots_ids_json:  Mapped[str]           = mapped_column(String, default="[]")
    power_ids_json:  Mapped[str]           = mapped_column(String, default="[]")
    caboose_id:      Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("cars.id"), nullable=True)
    available_spots: Mapped[int]           = mapped_column(Integer, default=0)
    built_at: Mapped[Optional[float]] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String, default="draft")  # "draft" | "active" | "complete"
    train_number: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    train_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    departure_time: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    engineer: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    conductor: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    special_instructions: Mapped[Optional[str]] = mapped_column(String, nullable=True)
