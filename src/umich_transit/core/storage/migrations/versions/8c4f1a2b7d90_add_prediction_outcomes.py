"""add prediction outcomes

Revision ID: 8c4f1a2b7d90
Revises: 5617d871fb94
Create Date: 2026-08-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "8c4f1a2b7d90"
down_revision: Union[str, Sequence[str], None] = "5617d871fb94"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "prediction_outcomes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("prediction_id", sa.Integer(), nullable=False),
        sa.Column("arrival_id", sa.Integer(), nullable=False),
        sa.Column("route_id", sa.String(), nullable=False),
        sa.Column("stop_id", sa.String(), nullable=False),
        sa.Column("vehicle_id", sa.String(), nullable=False),
        sa.Column("prediction_captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("predicted_arrival_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actual_arrival_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("prediction_horizon_s", sa.Float(), nullable=False),
        sa.Column("signed_error_s", sa.Float(), nullable=False),
        sa.Column("absolute_error_s", sa.Float(), nullable=False),
        sa.Column("detected_via", sa.String(), nullable=False),
        sa.Column("match_version", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["prediction_id"], ["predictions.id"]),
        sa.ForeignKeyConstraint(["arrival_id"], ["arrivals.id"]),
        sa.ForeignKeyConstraint(["route_id"], ["routes.id"]),
        sa.ForeignKeyConstraint(["stop_id"], ["stops.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("prediction_id", name="uq_prediction_outcomes_prediction"),
        sa.UniqueConstraint("arrival_id", name="uq_prediction_outcomes_arrival"),
    )
    op.create_index(
        "ix_prediction_outcomes_route_stop_actual",
        "prediction_outcomes",
        ["route_id", "stop_id", "actual_arrival_at"],
        unique=False,
    )
    op.create_table(
        "reliability_profiles",
        sa.Column("profile_key", sa.String(), nullable=False),
        sa.Column("scope", sa.String(), nullable=False),
        sa.Column("route_id", sa.String(), nullable=False),
        sa.Column("stop_id", sa.String(), nullable=True),
        sa.Column("dow", sa.Integer(), nullable=True),
        sa.Column("hour", sa.Integer(), nullable=False),
        sa.Column("correction_s", sa.Float(), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["route_id"], ["routes.id"]),
        sa.ForeignKeyConstraint(["stop_id"], ["stops.id"]),
        sa.PrimaryKeyConstraint("profile_key"),
    )
    op.create_index(
        "ix_reliability_profiles_lookup",
        "reliability_profiles",
        ["route_id", "stop_id", "dow", "hour"],
        unique=False,
    )
    op.create_table(
        "evaluation_reports",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("total_sample_count", sa.Integer(), nullable=False),
        sa.Column("training_sample_count", sa.Integer(), nullable=False),
        sa.Column("holdout_sample_count", sa.Integer(), nullable=False),
        sa.Column("match_version", sa.String(), nullable=False),
        sa.Column("model_version", sa.String(), nullable=False),
        sa.Column("metrics_json", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("evaluation_reports")
    op.drop_index("ix_reliability_profiles_lookup", table_name="reliability_profiles")
    op.drop_table("reliability_profiles")
    op.drop_index(
        "ix_prediction_outcomes_route_stop_actual",
        table_name="prediction_outcomes",
    )
    op.drop_table("prediction_outcomes")
