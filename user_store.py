"""Cluster-level user storage backed by SQLAlchemy."""

from __future__ import annotations

from passlib.context import CryptContext
from sqlalchemy.orm import Session

import config
from database import SessionLocal
from models import ClusterUser

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

def init_user_store() -> None:
    """Verify central user storage connectivity."""
    from database import init_db

    init_db()


def _get_session() -> Session:
    return SessionLocal()


def upsert_cluster_user(username: str, email: str, password: str) -> None:
    """Create or update a user record in central store."""
    password_hash = pwd_context.hash(password)
    with _get_session() as db:
        user = db.get(ClusterUser, username)
        if user is None:
            db.add(
                ClusterUser(
                    username=username,
                    email=email,
                    password_hash=password_hash,
                    gpu_hours_quota=config.GPU_HOURS_DEFAULT_QUOTA,
                )
            )
        else:
            user.email = email
            user.password_hash = password_hash
        db.commit()


def get_cluster_user(username: str) -> dict[str, str | float] | None:
    """Return cluster user info by username."""
    with _get_session() as db:
        user = db.get(ClusterUser, username)
    if user is None:
        return None
    return {
        "username": str(user.username),
        "email": str(user.email),
        "gpu_hours_quota": float(user.gpu_hours_quota or 0.0),
        "gpu_hours_used": float(user.gpu_hours_used or 0.0),
        "gpu_hours_frozen": float(user.gpu_hours_frozen or 0.0),
    }


def get_cluster_user_sync_record(username: str) -> dict[str, str] | None:
    """Return identity fields required to sync a user to one node."""
    with _get_session() as db:
        user = db.get(ClusterUser, username)
    if user is None:
        return None
    return {
        "username": str(user.username),
        "email": str(user.email),
        "password_hash": str(user.password_hash),
    }


def verify_cluster_user_password(username: str, password: str) -> bool:
    """Verify central-store password for a user."""
    with _get_session() as db:
        user = db.get(ClusterUser, username)
    if user is None:
        return False
    return pwd_context.verify(password, str(user.password_hash))
