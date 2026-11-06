# SPDX-FileCopyrightText: 2026 David Dalzell
# SPDX-License-Identifier: MIT

from typing import Optional
from pydantic import BaseModel, field_validator


class CarCreate(BaseModel):
    car_type: str
    color: str = ""
    car_number: str = ""
    reporting_marks: str = ""
    photo_path: str = ""
    current_location_id: Optional[int] = None


class CarUpdate(BaseModel):
    car_type: Optional[str] = None
    color: Optional[str] = None
    car_number: Optional[str] = None
    reporting_marks: Optional[str] = None
    current_location_id: Optional[int] = None
    photo_path: Optional[str] = None


class TrackCreate(BaseModel):
    """Create/update a Track."""
    name: str
    location_type: str = "yard"
    location_id: Optional[int] = None
    car_capacity: Optional[int] = None


class LocationCreate(BaseModel):
    """Create/update a Location (formerly SwitchingArea)."""
    name: str
    # Optional in the UI (blank field sends null); fall back to the model default.
    car_capacity: Optional[int] = 10

    @field_validator("car_capacity")
    @classmethod
    def _default_capacity(cls, v):
        return 10 if v is None else v


class MoveRequest(BaseModel):
    """Reorder a track or industry within its parent."""
    direction: str  # "up" | "down"


class DispatchBuildRequest(BaseModel):
    origin_location_id: int
    location_id: int
    destination_location_id: int
    excluded_car_ids: list[int] = []


class DispatchRebuildRequest(BaseModel):
    excluded_car_ids: list[int] = []


class DispatchPowerUpdate(BaseModel):
    power_ids: list[int] = []
    caboose_id: Optional[int] = None


class DispatchPlanIdentityUpdate(BaseModel):
    train_number: Optional[str] = None
    train_name: Optional[str] = None
    departure_time: Optional[str] = None
    engineer: Optional[str] = None
    conductor: Optional[str] = None
    special_instructions: Optional[str] = None


class DispatchPlanStatusUpdate(BaseModel):
    status: str  # "draft" | "active" | "complete"


class IndustryCreate(BaseModel):
    name: str
    location_id: int
    accepted_car_types: str = ""
    commodities: str = ""
    industry_role: str = "consumer"
    inbound_car_types: str = ""
    outbound_commodities: str = ""
    outbound_car_types: str = ""
    spot_numbers: str = ""


class WaybillCreate(BaseModel):
    name: str = ""
    origin_id: Optional[int] = None
    destination_id: Optional[int] = None
    industry_id: Optional[int] = None
    commodity: str = ""
    is_empty: bool = False
    required_car_type: Optional[str] = None
    is_priority: bool = False


class CarTypeCreate(BaseModel):
    name: str


class CarImportRow(BaseModel):
    reporting_marks: str
    car_number: str
    car_type: str = "other"
    color: str = ""


class CarImportCommit(BaseModel):
    cars: list[CarImportRow]
    mode: str = "add"


class GenerateWaybillsRequest(BaseModel):
    origin_location_id: Optional[int] = None  # ignored — waybills are generated for all staging+yard locations
    replace: bool = False


class CommodityCarTypeMapCreate(BaseModel):
    commodity: str
    car_type: str


class CommodityCarTypeMapUpdate(BaseModel):
    car_type: str


class CarSlotAssignment(BaseModel):
    slot_index: int
    waybill_id: Optional[int] = None


class CarSlotsUpdate(BaseModel):
    slots: list[CarSlotAssignment]


class AnalyzePhotoRequest(BaseModel):
    photo_path: str


class StylizeRequest(BaseModel):
    photo_path: str


class IndustrySuggestRequest(BaseModel):
    description: str


class CommoditySuggestRequest(BaseModel):
    commodity: str


class SessionCarResult(BaseModel):
    car_id: int
    status: str                         # "done" or "cp"
    location_id: Optional[int] = None  # required for cp cars


class SessionEndRequest(BaseModel):
    cars: list[SessionCarResult]


class LayoutSettingsUpdate(BaseModel):
    clock_start_time: str = "08:00"
    clock_speed: int = 4
    ops_mode: str = "free"
    max_train_length: Optional[int] = None


class DeleteUploadRequest(BaseModel):
    path: str


class DeleteUploadsRequest(BaseModel):
    paths: list[str]
