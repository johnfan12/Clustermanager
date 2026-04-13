"""add cluster user approval fields"""

from alembic import op
import sqlalchemy as sa


revision = "20260413_000007"
down_revision = "20260409_000006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cluster_users",
        sa.Column(
            "register_status",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'approved'"),
        ),
    )
    op.add_column(
        "cluster_users",
        sa.Column("approved_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "cluster_users",
        sa.Column("approved_by", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_cluster_users_register_status",
        "cluster_users",
        ["register_status"],
        unique=False,
    )
    op.execute(
        """
        UPDATE cluster_users
        SET register_status = 'approved',
            approved_at = created_at,
            approved_by = 'system'
        WHERE register_status IS NULL OR register_status = 'approved'
        """
    )


def downgrade() -> None:
    op.drop_index("ix_cluster_users_register_status", table_name="cluster_users")
    op.drop_column("cluster_users", "approved_by")
    op.drop_column("cluster_users", "approved_at")
    op.drop_column("cluster_users", "register_status")
