# SPDX-FileCopyrightText: 2026 David Dalzell
# SPDX-License-Identifier: MIT

"""Seed the public (demo) schema with the Millbrook & Western sample layout.

Idempotent: truncates all tenant tables before reinserting, so it can be
called repeatedly (e.g. by the nightly reset cron).
"""

import sys
import os
from datetime import datetime, timedelta
from pathlib import Path

# Allow running as `python -m admin.seed_demo` from repo root
sys.path.insert(0, str(Path(__file__).parent.parent))


_SCHEMA = "public"

_CARS = [
    # (reporting_marks, number, car_type, color)
    ("MBW", "1042", "covered hopper", "Gray"),
    ("MBW", "1078", "covered hopper", "Gray"),
    ("MBW", "1091", "covered hopper", "Gray"),
    ("MBW", "2011", "tank car", "Black"),
    ("MBW", "2034", "tank car", "Black"),
    ("MBW", "2056", "tank car", "Silver"),
    ("SP",  "403217", "boxcar", "Red"),
    ("UP",  "512388", "boxcar", "Yellow"),
    ("MBW", "3001", "boxcar", "Brown"),
    ("MBW", "4012", "flatcar", "Black"),
    ("MBW", "4025", "flatcar", "Black"),
    ("SP",  "601442", "flatcar", "Rust"),
    ("MBW", "5003", "gondola", "Black"),
    ("MBW", "5017", "gondola", "Black"),
    ("MBW", "9001", "caboose", "Red"),
]

_COMMODITY_MAP = [
    ("grain",     "covered hopper"),
    ("crude oil", "tank car"),
    ("lumber",    "flatcar"),
    ("coal",      "gondola"),
    ("general freight", "boxcar"),
]


def _write_movement_logs(db, history):
    """Write movement log entries with timestamps relative to now (2 hrs ago, 8-min intervals)."""
    from models import MovementLog
    base_time = datetime.utcnow() - timedelta(hours=2)
    for i, (car, from_loc, to_loc) in enumerate(history):
        db.add(MovementLog(
            car_id=car.id,
            timestamp=base_time + timedelta(minutes=i * 8),
            from_location_id=from_loc.id,
            to_location_id=to_loc.id,
            operator_email="dispatcher@mbw.demo",
            note="",
        ))


def regenerate_movement_logs(db):
    """Replace movement_logs with fresh timestamped entries based on current DB state.

    Called after cloning the demo-template schema so timestamps are always
    relative to the moment of reset rather than when the template was last edited.
    """
    from models import Car, Location, MovementLog
    db.query(MovementLog).delete(synchronize_session=False)
    db.flush()

    cars = db.query(Car).filter(Car.car_type != "caboose").limit(10).all()
    locations = db.query(Location).all()
    if len(cars) < 2 or len(locations) < 2:
        db.commit()
        return

    history = []
    for i, car in enumerate(cars):
        from_loc = locations[i % len(locations)]
        to_loc = locations[(i + 1) % len(locations)]
        history.append((car, from_loc, to_loc))

    _write_movement_logs(db, history)
    db.commit()


def seed_demo():
    from dotenv import load_dotenv
    load_dotenv()

    from database import SessionLocal, DEFAULT_CAR_TYPES
    from sqlalchemy import text
    from models import (
        Car, CarType, CommodityCarTypeMap, DispatchPlan,
        Industry, Location, MovementLog, SwitchingArea, Waybill,
    )

    db = SessionLocal()
    try:
        db.execute(text(f'SET search_path TO "{_SCHEMA}", public'))

        # ── Truncate in reverse FK order ────────────────────────────────────
        for model in (DispatchPlan, MovementLog, Waybill, Car,
                      CommodityCarTypeMap, Industry, Location, SwitchingArea, CarType):
            db.query(model).delete(synchronize_session=False)
        db.flush()

        # ── Car types ────────────────────────────────────────────────────────
        static_dir = Path("static/images/car-types")
        car_type_objs = {}
        for name in DEFAULT_CAR_TYPES:
            ct = CarType(name=name)
            slug = name.replace(" ", "-")
            for ext in (".svg", ".png", ".jpg", ".jpeg", ".webp"):
                if (static_dir / f"{slug}{ext}").exists():
                    ct.default_photo_path = str(static_dir / f"{slug}{ext}")
                    break
            db.add(ct)
            car_type_objs[name] = ct
        db.flush()

        # ── Commodity map ────────────────────────────────────────────────────
        for commodity, car_type in _COMMODITY_MAP:
            db.add(CommodityCarTypeMap(commodity=commodity, car_type=car_type))
        db.flush()

        # ── Switching area ───────────────────────────────────────────────────
        yard_area = SwitchingArea(name="Millbrook Yard", car_capacity=20)
        db.add(yard_area)
        db.flush()

        # ── Locations ────────────────────────────────────────────────────────
        loc_yard = Location(name="Millbrook Yard", location_type="yard",
                            switching_area_id=yard_area.id, car_capacity=20)
        loc_grain = Location(name="Riverside Grain", location_type="industry",
                             switching_area_id=yard_area.id, car_capacity=6)
        loc_fuel = Location(name="Valley Fuel", location_type="industry",
                            switching_area_id=yard_area.id, car_capacity=4)
        loc_lumber = Location(name="Millbrook Lumber", location_type="industry",
                              switching_area_id=yard_area.id, car_capacity=4)
        loc_staging = Location(name="West Staging", location_type="staging", car_capacity=30)
        for loc in (loc_yard, loc_grain, loc_fuel, loc_lumber, loc_staging):
            db.add(loc)
        db.flush()

        # ── Industries ───────────────────────────────────────────────────────
        db.add(Industry(
            name="Riverside Grain Elevator",
            location_id=loc_grain.id,
            industry_role="consumer",
            accepted_car_types="covered hopper",
            commodities="grain",
            inbound_car_types="covered hopper",
        ))
        db.add(Industry(
            name="Valley Fuel Depot",
            location_id=loc_fuel.id,
            industry_role="consumer",
            accepted_car_types="tank car",
            commodities="crude oil",
            inbound_car_types="tank car",
        ))
        db.add(Industry(
            name="Millbrook Lumber Co.",
            location_id=loc_lumber.id,
            industry_role="consumer",
            accepted_car_types="flatcar",
            commodities="lumber",
            inbound_car_types="flatcar",
        ))
        db.flush()

        # ── Cars + waybills ──────────────────────────────────────────────────
        # Destination cycling per car type
        type_destinations = {
            "covered hopper": (loc_grain,   "grain"),
            "tank car":       (loc_fuel,    "crude oil"),
            "flatcar":        (loc_lumber,  "lumber"),
            "gondola":        (loc_yard,    "coal"),
            "boxcar":         (loc_yard,    "general freight"),
            "caboose":        (None,        ""),
        }

        # Spread cars across locations for a realistic picture
        location_cycle = [loc_staging, loc_yard, loc_grain, loc_fuel, loc_lumber]
        loc_idx = 0

        car_objs = []
        for marks, number, car_type, color in _CARS:
            # Look up the default photo from the matching car type
            photo = ""
            ct = car_type_objs.get(car_type)
            if ct and ct.default_photo_path:
                photo = ct.default_photo_path

            current_loc = location_cycle[loc_idx % len(location_cycle)]
            loc_idx += 1

            car = Car(
                reporting_marks=marks,
                car_number=number,
                car_type=car_type,
                color=color,
                photo_path=photo,
                current_location_id=current_loc.id,
                active_waybill_slot=0,
            )
            db.add(car)
            db.flush()
            car_objs.append((car, current_loc))

            dest_loc, commodity = type_destinations.get(car_type, (None, ""))
            if dest_loc is None:
                continue

            # Slot 0 — current move: from current location to destination
            db.add(Waybill(
                car_id=car.id,
                slot_index=0,
                origin_id=current_loc.id,
                destination_id=dest_loc.id,
                commodity=commodity,
                required_car_type=car_type,
                is_empty=False,
            ))
            # Slot 1 — return empty to staging
            db.add(Waybill(
                car_id=car.id,
                slot_index=1,
                origin_id=dest_loc.id,
                destination_id=loc_staging.id,
                commodity="",
                required_car_type=car_type,
                is_empty=True,
            ))
            # Slot 2 — reload from staging to destination
            db.add(Waybill(
                car_id=car.id,
                slot_index=2,
                origin_id=loc_staging.id,
                destination_id=dest_loc.id,
                commodity=commodity,
                required_car_type=car_type,
                is_empty=False,
            ))

        db.flush()

        # ── Movement log (simulated prior session) ───────────────────────────
        history = [
            (car_objs[0][0],  loc_staging, loc_yard),
            (car_objs[1][0],  loc_staging, loc_yard),
            (car_objs[3][0],  loc_staging, loc_fuel),
            (car_objs[6][0],  loc_staging, loc_yard),
            (car_objs[9][0],  loc_staging, loc_lumber),
            (car_objs[2][0],  loc_yard,    loc_grain),
            (car_objs[4][0],  loc_yard,    loc_fuel),
            (car_objs[10][0], loc_yard,    loc_lumber),
            (car_objs[12][0], loc_yard,    loc_yard),
            (car_objs[5][0],  loc_staging, loc_fuel),
        ]
        _write_movement_logs(db, history)

        # ── Dispatch plan (pre-built consist to show Dispatcher tab) ─────────
        import json, time as _time
        setout_ids = [c.id for c, loc in car_objs if loc == loc_staging and c.car_type != "caboose"][:4]
        pickup_ids = [c.id for c, loc in car_objs if loc == loc_yard and c.car_type != "caboose"][:3]
        plan = DispatchPlan(
            plan_type="switching",
            origin_location_id=loc_staging.id,
            switching_area_id=yard_area.id,
            destination_location_id=loc_yard.id,
            setout_ids_json=json.dumps(setout_ids),
            pickup_ids_json=json.dumps(pickup_ids),
            spots_ids_json=json.dumps([]),
            available_spots=len(setout_ids),
            built_at=_time.time(),
            status="draft",
            train_number="MBW-101",
            train_name="Millbrook Local",
        )
        db.add(plan)

        db.commit()
        print(f"[seed_demo] Millbrook & Western seeded: "
              f"{len(_CARS)} cars, {len(_COMMODITY_MAP)} commodity mappings, "
              f"4 locations, 3 industries, 1 dispatch plan")

    finally:
        db.close()


if __name__ == "__main__":
    seed_demo()
