"""add central billing tables

Revision ID: 20260323_000003
Revises: 20260323_000002
Create Date: 2026-03-23
"""

from alembic import op
import sqlalchemy as sa


revision = "20260323_000003"
down_revision = "20260323_000002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cluster_instance_states",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("node_id", sa.String(length=64), nullable=False),
        sa.Column("node_instance_id", sa.Integer(), nullable=False),
        sa.Column("container_name", sa.String(length=128), nullable=False),
        sa.Column("gpu_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "status", sa.String(length=32), nullable=False, server_default="stopped"
        ),
        sa.Column("node_online", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_billed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["username"], ["cluster_users.username"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("node_id", "node_instance_id", name="uq_cluster_instance_node"),
    )
    op.create_index(
        "ix_cluster_instance_states_id", "cluster_instance_states", ["id"], unique=False
    )
    op.create_index(
        "ix_cluster_instance_states_node_id",
        "cluster_instance_states",
        ["node_id"],
        unique=False,
    )
    op.create_index(
        "ix_cluster_instance_states_username",
        "cluster_instance_states",
        ["username"],
        unique=False,
    )

    op.create_table(
        "cluster_gpu_hour_ledgers",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("node_id", sa.String(length=64), nullable=True),
        sa.Column("node_instance_id", sa.Integer(), nullable=True),
        sa.Column("container_name", sa.String(length=128), nullable=True),
        sa.Column(
            "delta_gpu_hours", sa.Float(), nullable=False, server_default="0"
        ),
        sa.Column(
            "reason", sa.String(length=64), nullable=False, server_default="settlement"
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["username"], ["cluster_users.username"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_cluster_gpu_hour_ledgers_id",
        "cluster_gpu_hour_ledgers",
        ["id"],
        unique=False,
    )
    op.create_index(
        "ix_cluster_gpu_hour_ledgers_node_id",
        "cluster_gpu_hour_ledgers",
        ["node_id"],
        unique=False,
    )
    op.create_index(
        "ix_cluster_gpu_hour_ledgers_node_instance_id",
        "cluster_gpu_hour_ledgers",
        ["node_instance_id"],
        unique=False,
    )
    op.create_index(
        "ix_cluster_gpu_hour_ledgers_username",
        "cluster_gpu_hour_ledgers",
        ["username"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_cluster_gpu_hour_ledgers_username", table_name="cluster_gpu_hour_ledgers"
    )
    op.drop_index(
        "ix_cluster_gpu_hour_ledgers_node_instance_id",
        table_name="cluster_gpu_hour_ledgers",
    )
    op.drop_index(
        "ix_cluster_gpu_hour_ledgers_node_id", table_name="cluster_gpu_hour_ledgers"
    )
    op.drop_index("ix_cluster_gpu_hour_ledgers_id", table_name="cluster_gpu_hour_ledgers")
    op.drop_table("cluster_gpu_hour_ledgers")

    op.drop_index(
        "ix_cluster_instance_states_username", table_name="cluster_instance_states"
    )
    op.drop_index(
        "ix_cluster_instance_states_node_id", table_name="cluster_instance_states"
    )
    op.drop_index("ix_cluster_instance_states_id", table_name="cluster_instance_states")
    op.drop_table("cluster_instance_states")
