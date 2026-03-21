"""Cluster-level user storage backed by SQLAlchemy."""

from __future__ import annotations

from passlib.context import CryptContext
from sqlalchemy.orm import Session

from database import SessionLocal
from models import ClusterUser

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

def init_user_store() -> None:
    """Initialize central user storage schema."""
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
                )
            )
        else:
            user.email = email
            user.password_hash = password_hash
        db.commit()


def get_cluster_user(username: str) -> dict[str, str] | None:
    """Return cluster user info by username."""
    with _get_session() as db:
        user = db.get(ClusterUser, username)
    if user is None:
        return None
    return {"username": str(user.username), "email": str(user.email)}


def verify_cluster_user_password(username: str, password: str) -> bool:
    """Verify central-store password for a user."""
    with _get_session() as db:
        user = db.get(ClusterUser, username)
    if user is None:
        return False
    return pwd_context.verify(password, str(user.password_hash))
