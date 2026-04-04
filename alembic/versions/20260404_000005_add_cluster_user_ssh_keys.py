"""add cluster user ssh keys

Revision ID: 20260404_000005
Revises: 20260401_000004
Create Date: 2026-04-04
"""

from alembic import op
import sqlalchemy as sa


revision = "20260404_000005"
down_revision = "20260401_000004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cluster_user_ssh_keys",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("public_key", sa.Text(), nullable=False),
        sa.Column("remark", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("fingerprint", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["username"],
            ["cluster_users.username"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "username",
            "fingerprint",
            name="uq_cluster_user_ssh_keys_username_fingerprint",
        ),
    )
    op.create_index(
        op.f("ix_cluster_user_ssh_keys_id"),
        "cluster_user_ssh_keys",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_cluster_user_ssh_keys_username"),
        "cluster_user_ssh_keys",
        ["username"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_cluster_user_ssh_keys_username"), table_name="cluster_user_ssh_keys")
    op.drop_index(op.f("ix_cluster_user_ssh_keys_id"), table_name="cluster_user_ssh_keys")
    op.drop_table("cluster_user_ssh_keys")
