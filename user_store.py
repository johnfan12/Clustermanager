"""Tiny SQLite user store for the simplified console."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import base64
import hashlib
import hmac
import os
from pathlib import Path
import re
import secrets
import sqlite3

from fastapi import HTTPException
from dotenv import load_dotenv

from auth import Principal

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
RUNTIME_DIR = BASE_DIR / os.environ.get("SIMPLE_RUNTIME_DIR", "runtime")
DATABASE_PATH = Path(
    os.environ.get("SIMPLE_USERS_DB", str(RUNTIME_DIR / "simple-cluster-users.db"))
)
PASSWORD_ITERATIONS = int(os.environ.get("SIMPLE_PASSWORD_HASH_ITERATIONS", "210000"))
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


@dataclass(frozen=True)
class AccountUser:
    """Registered console account."""

    username: str
    is_admin: bool


def init_user_store() -> None:
    """Create the account table if needed."""
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS console_users (
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                is_admin INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.commit()


def _normalize_username(username: str) -> str:
    normalized = username.strip()
    if not USERNAME_RE.fullmatch(normalized):
        raise HTTPException(
            status_code=400,
            detail="Username can only contain letters, numbers, dot, dash, and underscore.",
        )
    return normalized


def _validate_password(password: str) -> None:
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters.")
    if len(password) > 4096:
        raise HTTPException(status_code=400, detail="Password is too long.")


def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_ITERATIONS,
    )
    salt_text = base64.urlsafe_b64encode(salt).decode("ascii")
    digest_text = base64.urlsafe_b64encode(digest).decode("ascii")
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt_text}${digest_text}"


def _verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations_text, salt_text, digest_text = encoded.split("$", maxsplit=3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_text)
        salt = base64.urlsafe_b64decode(salt_text.encode("ascii"))
        expected = base64.urlsafe_b64decode(digest_text.encode("ascii"))
    except Exception:
        return False

    actual = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return hmac.compare_digest(actual, expected)


def _user_count(connection: sqlite3.Connection) -> int:
    row = connection.execute("SELECT COUNT(*) FROM console_users").fetchone()
    return int(row[0] if row else 0)


def create_account_user(
    username: str,
    password: str,
    *,
    first_user_admin: bool = True,
) -> AccountUser:
    """Register a new console account."""
    init_user_store()
    username = _normalize_username(username)
    _validate_password(password)

    with sqlite3.connect(DATABASE_PATH) as connection:
        is_admin = bool(first_user_admin and _user_count(connection) == 0)
        try:
            connection.execute(
                """
                INSERT INTO console_users (username, password_hash, is_admin, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    username,
                    _hash_password(password),
                    1 if is_admin else 0,
                    datetime.utcnow().isoformat(),
                ),
            )
            connection.commit()
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="Username is already registered.") from exc

    return AccountUser(username=username, is_admin=is_admin)


def authenticate_account_user(username: str, password: str) -> Principal:
    """Authenticate a registered console account."""
    init_user_store()
    username = username.strip()
    if not username or not password:
        raise HTTPException(status_code=401, detail="Invalid username or password.")

    with sqlite3.connect(DATABASE_PATH) as connection:
        row = connection.execute(
            "SELECT username, password_hash, is_admin FROM console_users WHERE username = ?",
            (username,),
        ).fetchone()

    if row is None or not _verify_password(password, str(row[1])):
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    return Principal(username=str(row[0]), is_admin=bool(row[2]))


def account_user_exists(username: str) -> bool:
    """Return whether a console account exists."""
    init_user_store()
    with sqlite3.connect(DATABASE_PATH) as connection:
        row = connection.execute(
            "SELECT 1 FROM console_users WHERE username = ?",
            (username.strip(),),
        ).fetchone()
    return row is not None
