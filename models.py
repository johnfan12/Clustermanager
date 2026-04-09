"""ORM models for Clustermanager."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

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
    gpu_hours_last_reset_period = Column(String(7), nullable=False, default="1970-01")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    instance_states = relationship(
        "ClusterInstanceState", back_populates="user", cascade="all, delete-orphan"
    )
    gpu_hour_ledgers = relationship(
        "ClusterGPUHourLedger", back_populates="user", cascade="all, delete-orphan"
    )
    ssh_keys = relationship(
        "ClusterUserSSHKey", back_populates="user", cascade="all, delete-orphan"
    )
    agent_sessions = relationship(
        "ClusterAgentSession", back_populates="user", cascade="all, delete-orphan"
    )


class ClusterInstanceState(Base):
    """Billing/runtime state for one instance observed from a node."""

    __tablename__ = "cluster_instance_states"
    __table_args__ = (
        UniqueConstraint("node_id", "node_instance_id", name="uq_cluster_instance_node"),
    )

    id = Column(Integer, primary_key=True, index=True)
    username = Column(
        String(64),
        ForeignKey("cluster_users.username", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    node_id = Column(String(64), nullable=False, index=True)
    node_instance_id = Column(Integer, nullable=False)
    container_name = Column(String(128), nullable=False)
    gpu_count = Column(Integer, nullable=False, default=0)
    status = Column(String(32), nullable=False, default="stopped")
    node_online = Column(Boolean, nullable=False, default=True)
    last_seen_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_billed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    user = relationship("ClusterUser", back_populates="instance_states")


class ClusterGPUHourLedger(Base):
    """Central billing ledger rows."""

    __tablename__ = "cluster_gpu_hour_ledgers"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(
        String(64),
        ForeignKey("cluster_users.username", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    node_id = Column(String(64), nullable=True, index=True)
    node_instance_id = Column(Integer, nullable=True, index=True)
    container_name = Column(String(128), nullable=True)
    delta_gpu_hours = Column(Float, nullable=False, default=0.0)
    reason = Column(String(64), nullable=False, default="settlement")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    user = relationship("ClusterUser", back_populates="gpu_hour_ledgers")


class ClusterUserSSHKey(Base):
    """Cluster-wide SSH public keys owned by one user."""

    __tablename__ = "cluster_user_ssh_keys"
    __table_args__ = (
        UniqueConstraint(
            "username",
            "fingerprint",
            name="uq_cluster_user_ssh_keys_username_fingerprint",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    username = Column(
        String(64),
        ForeignKey("cluster_users.username", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    public_key = Column(Text, nullable=False)
    remark = Column(String(255), nullable=False, default="")
    fingerprint = Column(String(255), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    user = relationship("ClusterUser", back_populates="ssh_keys")


class ClusterAgentSession(Base):
    """Controller-side durable state for one agent-managed dev session."""

    __tablename__ = "cluster_agent_sessions"
    __table_args__ = (
        UniqueConstraint(
            "node_id",
            "node_instance_id",
            name="uq_cluster_agent_sessions_node_instance",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    username = Column(
        String(64),
        ForeignKey("cluster_users.username", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    node_id = Column(String(64), nullable=False, index=True)
    node_instance_id = Column(Integer, nullable=False)
    container_name = Column(String(128), nullable=False)
    display_name = Column(String(128), nullable=False)
    image_name = Column(String(255), nullable=False)
    desired_num_gpus = Column(Integer, nullable=False, default=0)
    desired_memory_gb = Column(Integer, nullable=False, default=8)
    expire_hours = Column(Integer, nullable=False, default=24)
    instance_status = Column(String(32), nullable=False, default="unknown")
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    user = relationship("ClusterUser", back_populates="agent_sessions")
