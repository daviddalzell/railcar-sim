import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, get_db
from main import app
from models import Car, CommodityCarTypeMap, Industry, Location, Waybill


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = Session()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture()
def client(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ── Factory helpers ────────────────────────────────────────────────────────────

def make_location(db, name, loc_type="staging"):
    loc = Location(name=name, location_type=loc_type)
    db.add(loc)
    db.flush()
    return loc


def make_industry(db, name, location_id, role="consumer",
                  inbound_commodities="", inbound_car_types="",
                  outbound_commodities="", outbound_car_types=""):
    ind = Industry(
        name=name,
        location_id=location_id,
        industry_role=role,
        commodities=inbound_commodities,
        inbound_car_types=inbound_car_types,
        outbound_commodities=outbound_commodities,
        outbound_car_types=outbound_car_types,
        accepted_car_types="",
    )
    db.add(ind)
    db.flush()
    return ind


def make_car(db, car_type="boxcar", location_id=None):
    car = Car(car_type=car_type, current_location_id=location_id)
    db.add(car)
    db.flush()
    return car


def make_waybill(db, origin_id, destination_id, is_empty=False,
                 required_car_type=None, industry_id=None,
                 car_id=None, slot_index=None, name=""):
    wb = Waybill(
        name=name,
        origin_id=origin_id,
        destination_id=destination_id,
        is_empty=is_empty,
        required_car_type=required_car_type,
        industry_id=industry_id,
        car_id=car_id,
        slot_index=slot_index,
        commodity="",
    )
    db.add(wb)
    db.flush()
    return wb


def make_commodity_map(db, commodity, car_type):
    entry = CommodityCarTypeMap(commodity=commodity, car_type=car_type)
    db.add(entry)
    db.flush()
    return entry
