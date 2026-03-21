"""PostgreSQL database setup for Clustermanager."""

from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from config import CLUSTER_DATABASE_URL


def _engine_kwargs() -> dict[str, object]:
    return {
        "future": True,
        "pool_pre_ping": True,
    }


engine = create_engine(CLUSTER_DATABASE_URL, **_engine_kwargs())
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)
Base = declarative_base()


def init_db() -> None:
    """Verify that the database is reachable.

    Schema creation is managed by Alembic migrations.
    """
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))


def get_db() -> Generator[Session, None, None]:
    """Provide a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
