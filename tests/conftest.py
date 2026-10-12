"""Shared pytest fixtures and the test-database safety guard.

Database tests run against a dedicated PostgreSQL database given by
``TEST_DATABASE_URL``. The guard in :func:`app.config.assert_safe_test_target`
refuses to run when the URL is missing, its name does not end in ``_test``, or
it resolves to the same host/port/database as ``DATABASE_URL``. Only after the
guard passes do we run migrations and (between tests) TRUNCATE. The application
database is never touched and ``drop_all`` is never used.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import (  # noqa: E402  (path setup must come first)
    UnsafeTestTarget,
    assert_safe_test_target,
    get_settings,
)

TRUNCATE_SQL = text(
    "TRUNCATE TABLE product_sizes, product_colors, products, sizes, colors, "
    "categories RESTART IDENTITY CASCADE"
)


def truncate_all(engine: Engine) -> None:
    """Remove all rows from the six tables (independent test DB only)."""
    with engine.begin() as connection:
        connection.execute(TRUNCATE_SQL)


def escape_config_value(value: str) -> str:
    """Escape ``%`` so the value survives ConfigParser interpolation.

    Alembic stores ``sqlalchemy.url`` in an INI value; a raw ``%`` (which is
    common in percent-encoded passwords) would be read back by
    ``ConfigParser`` interpolation and either be corrupted or raise. Doubling
    each ``%`` makes ``get_main_option`` return the original URL.
    """
    return value.replace("%", "%%")


def run_migrations(url: str) -> None:
    """Bring the database at ``url`` up to the latest revision."""
    from alembic import command
    from alembic.config import Config

    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", escape_config_value(url))
    command.upgrade(config, "head")


def _guarded_test_database_url() -> str:
    """Validate TEST_DATABASE_URL, skipping only when it is simply missing.

    A URL that is present but unsafe fails (never skips) so it can't look green.
    """
    settings = get_settings()
    app_url = settings.database_url
    test_url = settings.test_database_url
    try:
        assert_safe_test_target(app_url, test_url)
    except UnsafeTestTarget as exc:
        if not test_url:
            pytest.skip(f"database tests need TEST_DATABASE_URL: {exc}")
        raise pytest.fail.Exception(f"unsafe test database target: {exc}") from None
    assert test_url is not None
    return test_url


@pytest.fixture(scope="session")
def test_database_url() -> str:
    """Validate and return TEST_DATABASE_URL, or stop the DB tests safely."""
    return _guarded_test_database_url()


@pytest.fixture(scope="session")
def migrated_engine() -> Iterator[Engine]:
    """An engine against the test database, migrated to ``head``.

    Deliberately takes no fixture argument holding the URL: pytest echoes
    fixture argument values on setup errors, which would expose the DSN.
    When ``TEST_DATABASE_URL`` is set but the database cannot be reached this
    fails (rather than skipping), so an unreachable test database is never
    reported as a green result; only the exception type is shown.
    """
    test_url = _guarded_test_database_url()
    try:
        run_migrations(test_url)
        engine = create_engine(test_url, pool_pre_ping=True)
        with engine.connect():
            pass
    except OperationalError as exc:
        # `from None` suppresses the original exception, whose message/traceback
        # may echo the connection target.
        raise pytest.fail.Exception(
            f"test database unreachable: {type(exc).__name__}"
        ) from None
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture()
def db_engine(migrated_engine: Engine) -> Iterator[Engine]:
    """Function-scoped engine; the six tables are emptied after each test."""
    yield migrated_engine
    truncate_all(migrated_engine)


@pytest.fixture()
def db_session(db_engine: Engine) -> Iterator[Session]:
    """Function-scoped ORM session for tests that prefer the models."""
    factory = sessionmaker(bind=db_engine, expire_on_commit=False)
    with factory() as session:
        yield session
        session.rollback()
