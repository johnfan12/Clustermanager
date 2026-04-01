"""add cluster user gpu-hours reset period

Revision ID: 20260401_000004
Revises: 20260323_000003
Create Date: 2026-04-01
"""

from alembic import op
import sqlalchemy as sa


revision = "20260401_000004"
down_revision = "20260323_000003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cluster_users",
        sa.Column(
            "gpu_hours_last_reset_period",
            sa.String(length=7),
            nullable=False,
            server_default=sa.text("to_char(CURRENT_DATE, 'YYYY-MM')"),
        ),
    )


def downgrade() -> None:
    op.drop_column("cluster_users", "gpu_hours_last_reset_period")
