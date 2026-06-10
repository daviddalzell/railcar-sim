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


def init_db():
    from models import Car, Location, Industry, Waybill, MovementLog, CommodityCarTypeMap  # noqa: F401
    Base.metadata.create_all(bind=engine)
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
