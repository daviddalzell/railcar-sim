-- SPDX-FileCopyrightText: 2026 David Dalzell
-- SPDX-License-Identifier: AGPL-3.0-or-later

-- Waypoint initial schema for Supabase (Postgres)
-- Run this in the Supabase SQL Editor to create all tables.

CREATE TABLE IF NOT EXISTS alembic_version (
    version_num VARCHAR(32) NOT NULL,
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

CREATE TABLE IF NOT EXISTS switching_areas (
    id SERIAL PRIMARY KEY,
    name VARCHAR NOT NULL,
    car_capacity INTEGER NOT NULL DEFAULT 10
);

CREATE TABLE IF NOT EXISTS locations (
    id SERIAL PRIMARY KEY,
    name VARCHAR NOT NULL,
    location_type VARCHAR NOT NULL DEFAULT 'yard',
    switching_area_id INTEGER REFERENCES switching_areas(id),
    car_capacity INTEGER
);

CREATE TABLE IF NOT EXISTS industries (
    id SERIAL PRIMARY KEY,
    name VARCHAR NOT NULL,
    location_id INTEGER REFERENCES locations(id),
    accepted_car_types VARCHAR NOT NULL DEFAULT '',
    commodities VARCHAR NOT NULL DEFAULT '',
    industry_role VARCHAR NOT NULL DEFAULT 'consumer',
    inbound_car_types VARCHAR NOT NULL DEFAULT '',
    outbound_commodities VARCHAR NOT NULL DEFAULT '',
    outbound_car_types VARCHAR NOT NULL DEFAULT '',
    spot_numbers VARCHAR NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS cars (
    id SERIAL PRIMARY KEY,
    car_type VARCHAR NOT NULL,
    color VARCHAR NOT NULL DEFAULT '',
    car_number VARCHAR NOT NULL DEFAULT '',
    reporting_marks VARCHAR NOT NULL DEFAULT '',
    photo_path VARCHAR NOT NULL DEFAULT '',
    current_location_id INTEGER REFERENCES locations(id),
    active_waybill_slot INTEGER NOT NULL DEFAULT 0,
    cp_session_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS waybills (
    id SERIAL PRIMARY KEY,
    name VARCHAR NOT NULL DEFAULT '',
    car_id INTEGER REFERENCES cars(id),
    slot_index INTEGER,
    origin_id INTEGER REFERENCES locations(id),
    destination_id INTEGER REFERENCES locations(id),
    industry_id INTEGER REFERENCES industries(id),
    commodity VARCHAR NOT NULL DEFAULT '',
    is_empty BOOLEAN NOT NULL DEFAULT FALSE,
    required_car_type VARCHAR
);

CREATE TABLE IF NOT EXISTS movement_logs (
    id SERIAL PRIMARY KEY,
    car_id INTEGER NOT NULL REFERENCES cars(id),
    timestamp TIMESTAMP,
    from_location_id INTEGER REFERENCES locations(id),
    to_location_id INTEGER REFERENCES locations(id),
    note VARCHAR NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS commodity_car_type_map (
    id SERIAL PRIMARY KEY,
    commodity VARCHAR NOT NULL UNIQUE,
    car_type VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS car_types (
    id SERIAL PRIMARY KEY,
    name VARCHAR NOT NULL UNIQUE,
    default_photo_path VARCHAR
);

CREATE TABLE IF NOT EXISTS layout_settings (
    id SERIAL PRIMARY KEY,
    clock_start_time VARCHAR NOT NULL DEFAULT '08:00',
    clock_speed INTEGER NOT NULL DEFAULT 4,
    ops_mode VARCHAR NOT NULL DEFAULT 'free'
);

CREATE TABLE IF NOT EXISTS session_clock (
    id SERIAL PRIMARY KEY,
    started_at FLOAT,
    paused_at FLOAT,
    paused_accum_s FLOAT NOT NULL DEFAULT 0,
    start_time VARCHAR NOT NULL DEFAULT '08:00',
    speed INTEGER NOT NULL DEFAULT 4
);

CREATE TABLE IF NOT EXISTS dispatch_plan (
    id SERIAL PRIMARY KEY,
    plan_type VARCHAR NOT NULL DEFAULT 'switching',
    origin_location_id INTEGER REFERENCES locations(id),
    switching_area_id INTEGER REFERENCES switching_areas(id),
    destination_location_id INTEGER REFERENCES locations(id),
    setout_ids_json VARCHAR NOT NULL DEFAULT '[]',
    pickup_ids_json VARCHAR NOT NULL DEFAULT '[]',
    spots_ids_json VARCHAR NOT NULL DEFAULT '[]',
    power_ids_json VARCHAR NOT NULL DEFAULT '[]',
    caboose_id INTEGER REFERENCES cars(id),
    available_spots INTEGER NOT NULL DEFAULT 0,
    built_at FLOAT,
    status VARCHAR NOT NULL DEFAULT 'draft',
    train_number VARCHAR,
    train_name VARCHAR,
    departure_time VARCHAR,
    engineer VARCHAR,
    conductor VARCHAR,
    special_instructions VARCHAR
);

CREATE INDEX IF NOT EXISTS ix_switching_areas_id ON switching_areas(id);
CREATE INDEX IF NOT EXISTS ix_locations_id ON locations(id);
CREATE INDEX IF NOT EXISTS ix_industries_id ON industries(id);
CREATE INDEX IF NOT EXISTS ix_cars_id ON cars(id);
CREATE INDEX IF NOT EXISTS ix_waybills_id ON waybills(id);
CREATE INDEX IF NOT EXISTS ix_movement_logs_id ON movement_logs(id);
CREATE INDEX IF NOT EXISTS ix_commodity_car_type_map_id ON commodity_car_type_map(id);

-- Mark the Alembic migration as applied so 'alembic upgrade head' is a no-op
INSERT INTO alembic_version (version_num) VALUES ('55397423d9b2')
ON CONFLICT DO NOTHING;
