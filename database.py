from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = "sqlite:///./railcar.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
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
    "covered hopper", "refrigerator car", "caboose", "passenger car", "other",
]


def init_db():
    from models import Car, CarType, Location, Industry, Waybill, MovementLog, CommodityCarTypeMap, LayoutSettings, SessionClock  # noqa: F401
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if db.query(CarType).count() == 0:
            for name in DEFAULT_CAR_TYPES:
                db.add(CarType(name=name))
            db.commit()
    finally:
        db.close()
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
