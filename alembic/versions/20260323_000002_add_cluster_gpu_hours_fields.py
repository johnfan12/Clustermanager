"""add cluster user gpu-hours fields

Revision ID: 20260323_000002
Revises: 20260321_000001
Create Date: 2026-03-23
"""

from alembic import op
import sqlalchemy as sa


revision = "20260323_000002"
down_revision = "20260321_000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cluster_users",
        sa.Column("gpu_hours_quota", sa.Float(), nullable=False, server_default="100"),
    )
    op.add_column(
        "cluster_users",
        sa.Column("gpu_hours_used", sa.Float(), nullable=False, server_default="0"),
    )
    op.add_column(
        "cluster_users",
        sa.Column("gpu_hours_frozen", sa.Float(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("cluster_users", "gpu_hours_frozen")
    op.drop_column("cluster_users", "gpu_hours_used")
    op.drop_column("cluster_users", "gpu_hours_quota")
