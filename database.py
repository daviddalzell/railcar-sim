import os
from pathlib import Path
from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./railcar.db")

_is_sqlite = DATABASE_URL.startswith("sqlite")
_connect_args = {"check_same_thread": False} if _is_sqlite else {}
engine = create_engine(DATABASE_URL, connect_args=_connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


DEFAULT_CAR_TYPES = [
    "boxcar", "flatcar", "gondola", "tank car", "hopper",
    "covered hopper", "refrigerator car", "caboose", "passenger car", "locomotive", "other",
]


def init_db():
    from models import Car, CarType, Location, Industry, Waybill, MovementLog, CommodityCarTypeMap, LayoutSettings, SessionClock, SwitchingArea, DispatchPlan  # noqa: F401
    Base.metadata.create_all(bind=engine)
    if not _is_sqlite:
        # Postgres schema is managed by Alembic; only seed default data below.
        _seed_defaults()
        return
    # SQLite only: run column migrations so older local databases stay compatible.
    with engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE waybills ADD COLUMN required_car_type TEXT"))
            conn.commit()
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE industries ADD COLUMN industry_role TEXT DEFAULT 'consumer'"))
            conn.commit()
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE industries ADD COLUMN inbound_car_types TEXT DEFAULT ''"))
            conn.commit()
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE industries ADD COLUMN outbound_commodities TEXT DEFAULT ''"))
            conn.commit()
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE industries ADD COLUMN outbound_car_types TEXT DEFAULT ''"))
            conn.commit()
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE car_types ADD COLUMN default_photo_path TEXT"))
            conn.commit()
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE locations ADD COLUMN switching_area_id INTEGER REFERENCES switching_areas(id)"))
            conn.commit()
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE dispatch_plan ADD COLUMN spots_ids_json TEXT DEFAULT '[]'"))
            conn.commit()
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE dispatch_plan ADD COLUMN power_ids_json TEXT DEFAULT '[]'"))
            conn.commit()
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE dispatch_plan ADD COLUMN caboose_id INTEGER REFERENCES cars(id)"))
            conn.commit()
        except Exception:
            pass
        for col, defn in [
            ("train_number",          "TEXT"),
            ("train_name",            "TEXT"),
            ("departure_time",        "TEXT"),
            ("engineer",              "TEXT"),
            ("conductor",             "TEXT"),
            ("special_instructions",  "TEXT"),
            ("status",                "TEXT DEFAULT 'draft'"),
        ]:
            try:
                conn.execute(text(f"ALTER TABLE dispatch_plan ADD COLUMN {col} {defn}"))
                conn.commit()
            except Exception:
                pass
        try:
            conn.execute(text("ALTER TABLE layout_settings ADD COLUMN ops_mode TEXT DEFAULT 'free'"))
            conn.commit()
        except Exception:
            pass
        for col, table, defn in [
            ("car_capacity",     "locations",  "INTEGER"),
            ("spot_numbers",     "industries", "TEXT DEFAULT ''"),
            ("cp_session_count", "cars",       "INTEGER DEFAULT 0"),
        ]:
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {defn}"))
                conn.commit()
            except Exception:
                pass
        # One-time migration: move producer industries' data to outbound fields
        conn.execute(text("""
            UPDATE industries
            SET outbound_commodities = commodities,
                outbound_car_types   = accepted_car_types,
                commodities          = '',
                accepted_car_types   = ''
            WHERE industry_role = 'producer'
              AND (outbound_commodities IS NULL OR outbound_commodities = '')
        """))
        conn.commit()
    _seed_defaults()


def _seed_defaults():
    from models import CarType  # noqa: F401 — local import avoids circular dep
    db = SessionLocal()
    try:
        if db.query(CarType).count() == 0:
            for name in DEFAULT_CAR_TYPES:
                db.add(CarType(name=name))
            db.commit()
        else:
            existing = {ct.name for ct in db.query(CarType).all()}
            for name in DEFAULT_CAR_TYPES:
                if name not in existing:
                    db.add(CarType(name=name))
            db.commit()
        # Auto-assign bundled default images for car types that have none set
        static_dir = Path("static/images/car-types")
        if static_dir.exists():
            for ct in db.query(CarType).all():
                if ct.default_photo_path:
                    continue
                slug = ct.name.replace(" ", "-")
                for ext in (".svg", ".png", ".jpg", ".jpeg", ".webp"):
                    candidate = static_dir / f"{slug}{ext}"
                    if candidate.exists():
                        ct.default_photo_path = str(candidate)
                        break
            db.commit()
    finally:
        db.close()
