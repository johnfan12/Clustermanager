"""Cluster-level user storage for cross-node provisioning."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from passlib.context import CryptContext

from config import CLUSTER_USER_DB_PATH

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


def _get_conn() -> sqlite3.Connection:
    db_path = Path(CLUSTER_USER_DB_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def init_user_store() -> None:
    """Initialize central user storage schema."""
    with _get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cluster_users (
                username TEXT PRIMARY KEY,
                email TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.commit()


def upsert_cluster_user(username: str, email: str, password: str) -> None:
    """Create or update a user record in central store."""
    password_hash = pwd_context.hash(password)
    with _get_conn() as conn:
        conn.execute(
            """
            INSERT INTO cluster_users (username, email, password_hash)
            VALUES (?, ?, ?)
            ON CONFLICT(username) DO UPDATE SET
                email = excluded.email,
                password_hash = excluded.password_hash,
                updated_at = datetime('now')
            """,
            (username, email, password_hash),
        )
        conn.commit()


def get_cluster_user(username: str) -> dict[str, str] | None:
    """Return cluster user info by username."""
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT username, email FROM cluster_users WHERE username = ?",
            (username,),
        ).fetchone()
    if row is None:
        return None
    return {"username": str(row["username"]), "email": str(row["email"])}


def verify_cluster_user_password(username: str, password: str) -> bool:
    """Verify central-store password for a user."""
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT password_hash FROM cluster_users WHERE username = ?",
            (username,),
        ).fetchone()
    if row is None:
        return False
    return pwd_context.verify(password, str(row["password_hash"]))
