"""add cluster agent sessions

Revision ID: 20260409_000006
Revises: 20260404_000005
Create Date: 2026-04-09
"""

from alembic import op
import sqlalchemy as sa


revision = "20260409_000006"
down_revision = "20260404_000005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cluster_agent_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("node_id", sa.String(length=64), nullable=False),
        sa.Column("node_instance_id", sa.Integer(), nullable=False),
        sa.Column("container_name", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("image_name", sa.String(length=255), nullable=False),
        sa.Column("desired_num_gpus", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("desired_memory_gb", sa.Integer(), nullable=False, server_default="8"),
        sa.Column("expire_hours", sa.Integer(), nullable=False, server_default="24"),
        sa.Column(
            "instance_status",
            sa.String(length=32),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["username"],
            ["cluster_users.username"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "node_id",
            "node_instance_id",
            name="uq_cluster_agent_sessions_node_instance",
        ),
    )
    op.create_index(
        op.f("ix_cluster_agent_sessions_id"),
        "cluster_agent_sessions",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_cluster_agent_sessions_node_id"),
        "cluster_agent_sessions",
        ["node_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_cluster_agent_sessions_username"),
        "cluster_agent_sessions",
        ["username"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_cluster_agent_sessions_username"), table_name="cluster_agent_sessions")
    op.drop_index(op.f("ix_cluster_agent_sessions_node_id"), table_name="cluster_agent_sessions")
    op.drop_index(op.f("ix_cluster_agent_sessions_id"), table_name="cluster_agent_sessions")
    op.drop_table("cluster_agent_sessions")
