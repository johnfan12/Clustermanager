"""Database setup for Clustermanager."""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from config import CLUSTER_DATABASE_URL


def _engine_kwargs() -> dict[str, object]:
    url = make_url(CLUSTER_DATABASE_URL)
    kwargs: dict[str, object] = {
        "future": True,
        "pool_pre_ping": True,
    }
    if url.get_backend_name() == "sqlite":
        kwargs["connect_args"] = {"check_same_thread": False}
    return kwargs


engine = create_engine(CLUSTER_DATABASE_URL, **_engine_kwargs())
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)
Base = declarative_base()


def init_db() -> None:
    """Create database tables if they do not already exist."""
    from models import ClusterUser

    del ClusterUser
    Base.metadata.create_all(bind=engine)


def get_db() -> Generator[Session, None, None]:
    """Provide a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
