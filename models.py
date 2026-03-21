"""ORM models for Clustermanager."""

from datetime import datetime

from sqlalchemy import Column, DateTime, String

from database import Base


class ClusterUser(Base):
    """Central user storage for cross-node account management."""

    __tablename__ = "cluster_users"

    username = Column(String(64), primary_key=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
