"""initial_schema

Revision ID: 55397423d9b2
Revises:
Create Date: 2026-06-28

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '55397423d9b2'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'switching_areas',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('car_capacity', sa.Integer(), nullable=False, server_default='10'),
    )

    op.create_table(
        'locations',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('location_type', sa.String(), nullable=False, server_default='yard'),
        sa.Column('switching_area_id', sa.Integer(), sa.ForeignKey('switching_areas.id'), nullable=True),
        sa.Column('car_capacity', sa.Integer(), nullable=True),
    )

    op.create_table(
        'industries',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('location_id', sa.Integer(), sa.ForeignKey('locations.id'), nullable=True),
        sa.Column('accepted_car_types', sa.String(), nullable=False, server_default=''),
        sa.Column('commodities', sa.String(), nullable=False, server_default=''),
        sa.Column('industry_role', sa.String(), nullable=False, server_default='consumer'),
        sa.Column('inbound_car_types', sa.String(), nullable=False, server_default=''),
        sa.Column('outbound_commodities', sa.String(), nullable=False, server_default=''),
        sa.Column('outbound_car_types', sa.String(), nullable=False, server_default=''),
        sa.Column('spot_numbers', sa.String(), nullable=False, server_default=''),
    )

    op.create_table(
        'cars',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('car_type', sa.String(), nullable=False),
        sa.Column('color', sa.String(), nullable=False, server_default=''),
        sa.Column('car_number', sa.String(), nullable=False, server_default=''),
        sa.Column('reporting_marks', sa.String(), nullable=False, server_default=''),
        sa.Column('photo_path', sa.String(), nullable=False, server_default=''),
        sa.Column('current_location_id', sa.Integer(), sa.ForeignKey('locations.id'), nullable=True),
        sa.Column('active_waybill_slot', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('cp_session_count', sa.Integer(), nullable=False, server_default='0'),
    )

    op.create_table(
        'waybills',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(), nullable=False, server_default=''),
        sa.Column('car_id', sa.Integer(), sa.ForeignKey('cars.id'), nullable=True),
        sa.Column('slot_index', sa.Integer(), nullable=True),
        sa.Column('origin_id', sa.Integer(), sa.ForeignKey('locations.id'), nullable=True),
        sa.Column('destination_id', sa.Integer(), sa.ForeignKey('locations.id'), nullable=True),
        sa.Column('industry_id', sa.Integer(), sa.ForeignKey('industries.id'), nullable=True),
        sa.Column('commodity', sa.String(), nullable=False, server_default=''),
        sa.Column('is_empty', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('required_car_type', sa.String(), nullable=True),
    )

    op.create_table(
        'movement_logs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('car_id', sa.Integer(), sa.ForeignKey('cars.id'), nullable=False),
        sa.Column('timestamp', sa.DateTime(), nullable=True),
        sa.Column('from_location_id', sa.Integer(), sa.ForeignKey('locations.id'), nullable=True),
        sa.Column('to_location_id', sa.Integer(), sa.ForeignKey('locations.id'), nullable=True),
        sa.Column('note', sa.String(), nullable=False, server_default=''),
    )

    op.create_table(
        'commodity_car_type_map',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('commodity', sa.String(), nullable=False, unique=True),
        sa.Column('car_type', sa.String(), nullable=False),
    )

    op.create_table(
        'car_types',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(), nullable=False, unique=True),
        sa.Column('default_photo_path', sa.String(), nullable=True),
    )

    op.create_table(
        'layout_settings',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('clock_start_time', sa.String(), nullable=False, server_default='08:00'),
        sa.Column('clock_speed', sa.Integer(), nullable=False, server_default='4'),
        sa.Column('ops_mode', sa.String(), nullable=False, server_default='free'),
    )

    op.create_table(
        'session_clock',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('started_at', sa.Float(), nullable=True),
        sa.Column('paused_at', sa.Float(), nullable=True),
        sa.Column('paused_accum_s', sa.Float(), nullable=False, server_default='0'),
        sa.Column('start_time', sa.String(), nullable=False, server_default='08:00'),
        sa.Column('speed', sa.Integer(), nullable=False, server_default='4'),
    )

    op.create_table(
        'dispatch_plan',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('plan_type', sa.String(), nullable=False, server_default='switching'),
        sa.Column('origin_location_id', sa.Integer(), sa.ForeignKey('locations.id'), nullable=True),
        sa.Column('switching_area_id', sa.Integer(), sa.ForeignKey('switching_areas.id'), nullable=True),
        sa.Column('destination_location_id', sa.Integer(), sa.ForeignKey('locations.id'), nullable=True),
        sa.Column('setout_ids_json', sa.String(), nullable=False, server_default='[]'),
        sa.Column('pickup_ids_json', sa.String(), nullable=False, server_default='[]'),
        sa.Column('spots_ids_json', sa.String(), nullable=False, server_default='[]'),
        sa.Column('power_ids_json', sa.String(), nullable=False, server_default='[]'),
        sa.Column('caboose_id', sa.Integer(), sa.ForeignKey('cars.id'), nullable=True),
        sa.Column('available_spots', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('built_at', sa.Float(), nullable=True),
        sa.Column('status', sa.String(), nullable=False, server_default='draft'),
        sa.Column('train_number', sa.String(), nullable=True),
        sa.Column('train_name', sa.String(), nullable=True),
        sa.Column('departure_time', sa.String(), nullable=True),
        sa.Column('engineer', sa.String(), nullable=True),
        sa.Column('conductor', sa.String(), nullable=True),
        sa.Column('special_instructions', sa.String(), nullable=True),
    )

    op.create_index('ix_switching_areas_id', 'switching_areas', ['id'])
    op.create_index('ix_locations_id', 'locations', ['id'])
    op.create_index('ix_industries_id', 'industries', ['id'])
    op.create_index('ix_cars_id', 'cars', ['id'])
    op.create_index('ix_waybills_id', 'waybills', ['id'])
    op.create_index('ix_movement_logs_id', 'movement_logs', ['id'])
    op.create_index('ix_commodity_car_type_map_id', 'commodity_car_type_map', ['id'])


def downgrade() -> None:
    op.drop_table('dispatch_plan')
    op.drop_table('session_clock')
    op.drop_table('layout_settings')
    op.drop_table('car_types')
    op.drop_table('commodity_car_type_map')
    op.drop_table('movement_logs')
    op.drop_table('waybills')
    op.drop_table('cars')
    op.drop_table('industries')
    op.drop_table('locations')
    op.drop_table('switching_areas')
