"""SQLAlchemy engine, declarative base and the per-request session.

Other modules import :data:`Base` and :func:`get_session` (a FastAPI
dependency); the engine is created lazily from ``DATABASE_URL`` on first use so
that importing the models never requires a configured database.
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import MetaData, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

# A naming convention keeps constraint and index names stable, which is what
# makes Alembic autogenerate produce reproducible (and reviewable) diffs.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    """Return the process-wide engine, building it from DATABASE_URL on demand."""
    global _engine
    if _engine is None:
        _engine = create_engine(
            get_settings().require_database_url(), pool_pre_ping=True
        )
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    """Return the process-wide session factory (one engine, many sessions)."""
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _session_factory


def get_session() -> Iterator[Session]:
    """FastAPI dependency: yield one Session per request and close it after."""
    with get_session_factory()() as session:
        yield session


def __getattr__(name: str):
    """Expose ``engine`` lazily without requiring DATABASE_URL at import time."""
    if name == "engine":
        return get_engine()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
