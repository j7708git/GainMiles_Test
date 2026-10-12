"""Application configuration.

Settings are loaded from the project-root ``.env`` file, so the app, Alembic
and the tests all see the same values no matter which directory a command is
run from. The ``.env`` file is created by ``setup_env.py`` (see README).

This module also provides the small helpers the test suite uses to make sure a
test run can never touch the application database.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    """Typed view of the values read from the environment / ``.env``."""

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    database_url: str | None = None
    test_database_url: str | None = None

    def require_database_url(self) -> str:
        """Return ``DATABASE_URL`` or raise a short, credential-free error."""
        if not self.database_url or not self.database_url.strip():
            raise RuntimeError(
                "DATABASE_URL is not set. Create .env first (run: python setup_env.py)."
            )
        return self.database_url

    def require_test_database_url(self) -> str:
        """Return ``TEST_DATABASE_URL`` or raise a short, credential-free error."""
        if not self.test_database_url or not self.test_database_url.strip():
            raise RuntimeError(
                "TEST_DATABASE_URL is not set. Create .env first "
                "(run: python setup_env.py)."
            )
        return self.test_database_url


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings instance (cached)."""
    return Settings()


class UnsafeTestTarget(RuntimeError):
    """Raised when a test database target is missing or unsafe to reset."""


@dataclass(frozen=True)
class DatabaseTarget:
    """The parts of a connection URL that identify a database."""

    host: str | None
    port: int
    database: str | None


# PostgreSQL's default port; a URL that omits the port is treated as this.
_DEFAULT_POSTGRES_PORT = 5432

# Query-parameter names that could silently redirect the connection somewhere
# else; a guarded URL must not use them.
_FORBIDDEN_QUERY_KEYS = frozenset({"host", "hostaddr", "port", "dbname", "database"})


def normalize_db_host(host: str | None) -> str | None:
    """Treat the common loopback spellings as one host."""
    if host in {"localhost", "127.0.0.1", "::1"}:
        return "localhost"
    return host


def parse_database_target(url: str) -> DatabaseTarget:
    """Parse a PostgreSQL connection URL into a comparable target.

    Fail-closed: anything unexpected raises :class:`UnsafeTestTarget` with a
    short message that never contains the URL or its credentials.
    """
    from sqlalchemy.engine import make_url
    from sqlalchemy.exc import ArgumentError

    if not isinstance(url, str) or not url.strip():
        raise UnsafeTestTarget("database URL is empty")
    try:
        parsed = make_url(url)
    except (ArgumentError, ValueError, TypeError):
        # Do not chain: the original message may echo the value.
        raise UnsafeTestTarget("database URL could not be parsed") from None

    if parsed.get_backend_name() != "postgresql":
        raise UnsafeTestTarget("database URL must use the postgresql scheme")
    if not parsed.host:
        raise UnsafeTestTarget("database URL must include a host")
    if {key.lower() for key in parsed.query.keys()} & _FORBIDDEN_QUERY_KEYS:
        raise UnsafeTestTarget(
            "database URL must not override host/port/dbname via query parameters"
        )

    port = parsed.port if parsed.port is not None else _DEFAULT_POSTGRES_PORT
    return DatabaseTarget(normalize_db_host(parsed.host), port, parsed.database)


def assert_safe_test_target(app_url: str | None, test_url: str | None) -> DatabaseTarget:
    """Refuse to run DB tests unless the target is a dedicated, distinct database.

    Returns the parsed test target so callers can reuse it. Raises
    :class:`UnsafeTestTarget` when the URL is missing, not a plain PostgreSQL
    URL, has no host, overrides the connection via query parameters, its
    database name does not end in ``_test``, or it resolves to the same
    host/port/database as the application URL.
    """
    if not test_url or not test_url.strip():
        raise UnsafeTestTarget("TEST_DATABASE_URL is not set")
    target = parse_database_target(test_url)
    database = target.database or ""
    if not database:
        raise UnsafeTestTarget("TEST_DATABASE_URL has no database name")
    if not database.endswith("_test"):
        raise UnsafeTestTarget("test database name must end with '_test'")
    if app_url and app_url.strip() and parse_database_target(app_url) == target:
        raise UnsafeTestTarget("TEST_DATABASE_URL must differ from DATABASE_URL")
    return target
