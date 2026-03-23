"""ORM models for Clustermanager."""

from datetime import datetime

from sqlalchemy import Column, DateTime, Float, String

from database import Base


class ClusterUser(Base):
    """Central user storage for cross-node account management."""

    __tablename__ = "cluster_users"

    username = Column(String(64), primary_key=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    gpu_hours_quota = Column(Float, nullable=False, default=100.0)
    gpu_hours_used = Column(Float, nullable=False, default=0.0)
    gpu_hours_frozen = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
