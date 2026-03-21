"""create cluster_users"""

from alembic import op
import sqlalchemy as sa


revision = "20260321_000001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cluster_users",
        sa.Column("username", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_cluster_users_email", "cluster_users", ["email"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_cluster_users_email", table_name="cluster_users")
    op.drop_table("cluster_users")
