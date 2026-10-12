"""Environment and safety-guard tests — these need no database.

No literal credentials appear here: usernames and passwords are generated with
``secrets`` and every connection URL is built with SQLAlchemy's ``URL.create``.
The only literal password is the ``change-me`` placeholder documented in
``.env.example``, which is explicitly not a secret.
"""

from __future__ import annotations

import re
import secrets
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote

import pytest
import yaml
from sqlalchemy.engine import URL

import setup_env
from app import config as app_config
from app.config import (
    Settings,
    UnsafeTestTarget,
    assert_safe_test_target,
    parse_database_target,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_PATH = PROJECT_ROOT / "compose.yaml"

# Matches a Compose/container variable reference such as ${POSTGRES_DB} (also
# inside the escaped ``$${POSTGRES_DB}`` form used in healthchecks).
_ENV_REFERENCE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def rand_password() -> str:
    return secrets.token_urlsafe(16)


def pg_url(
    *,
    host: str | None = "localhost",
    port: int | None = 5432,
    database: str,
    user: str | None = None,
    password: str | None = None,
    query: dict[str, str] | None = None,
) -> str:
    """Build a PostgreSQL URL with generated credentials."""
    return URL.create(
        drivername="postgresql+psycopg",
        username=user if user is not None else secrets.token_urlsafe(6),
        password=password if password is not None else rand_password(),
        host=host,
        port=port,
        database=database,
        query=query or {},
    ).render_as_string(hide_password=False)


def make_example(tmp_path: Path) -> Path:
    example = tmp_path / ".env.example"
    example.write_text(
        "POSTGRES_USER=u\n"
        "POSTGRES_PASSWORD=change-me\n"
        "DATABASE_URL=postgresql+psycopg://u:change-me@localhost:55432/u\n",
        encoding="utf-8",
    )
    return example


def assert_safe_message(message: str) -> None:
    assert "://" not in message
    assert "\n" not in message
    assert message  # non-empty
    assert len(message) < 200


# --- configuration loading --------------------------------------------------


def test_env_file_resolves_to_project_root() -> None:
    assert app_config.ENV_FILE.is_absolute()
    assert app_config.ENV_FILE == PROJECT_ROOT / ".env"
    assert app_config.PROJECT_ROOT == PROJECT_ROOT
    assert app_config.ENV_FILE.name == ".env"


def test_missing_database_url_raises_safe_error() -> None:
    settings = Settings(_env_file=None, database_url=None, test_database_url=None)
    with pytest.raises(RuntimeError) as excinfo:
        settings.require_database_url()
    message = str(excinfo.value)
    assert "DATABASE_URL" in message
    # A short, credential-free message: no connection URL is leaked.
    assert "://" not in message
    assert "postgresql" not in message


def test_missing_test_database_url_raises_safe_error() -> None:
    settings = Settings(_env_file=None, database_url=None, test_database_url=None)
    with pytest.raises(RuntimeError) as excinfo:
        settings.require_test_database_url()
    assert_safe_message(str(excinfo.value))


# --- target guard: straightforward refusals ---------------------------------


def test_guard_rejects_missing_test_url() -> None:
    with pytest.raises(UnsafeTestTarget):
        assert_safe_test_target(pg_url(database="gainmiles"), None)


def test_guard_rejects_blank_test_url() -> None:
    with pytest.raises(UnsafeTestTarget):
        assert_safe_test_target(None, "   ")


def test_guard_rejects_database_without_test_suffix() -> None:
    with pytest.raises(UnsafeTestTarget):
        assert_safe_test_target(None, pg_url(database="gainmiles"))


def test_guard_rejects_same_target_across_host_spellings() -> None:
    app_url = pg_url(host="localhost", port=55432, database="gainmiles_test")
    test_url = pg_url(host="127.0.0.1", port=55432, database="gainmiles_test")
    with pytest.raises(UnsafeTestTarget):
        assert_safe_test_target(app_url, test_url)


def test_guard_rejects_default_port_alias() -> None:
    # An omitted port means 5432, so "no port" and an explicit 5432 are the
    # same target even across localhost spellings.
    app_url = pg_url(host="localhost", port=None, database="gainmiles_test")
    test_url = pg_url(host="127.0.0.1", port=5432, database="gainmiles_test")
    with pytest.raises(UnsafeTestTarget):
        assert_safe_test_target(app_url, test_url)


def test_guard_accepts_distinct_test_target() -> None:
    app_url = pg_url(host="localhost", port=55432, database="gainmiles")
    test_url = pg_url(host="127.0.0.1", port=55433, database="gainmiles_test")
    target = assert_safe_test_target(app_url, test_url)
    assert target.host == "localhost"  # 127.0.0.1 normalized
    assert target.port == 55433
    assert target.database == "gainmiles_test"


def test_default_port_is_applied_when_omitted() -> None:
    target = parse_database_target(pg_url(port=None, database="gainmiles_test"))
    assert target.port == 5432


# --- target guard: malformed and fail-closed cases --------------------------


def test_guard_rejects_malformed_url() -> None:
    with pytest.raises(UnsafeTestTarget) as excinfo:
        assert_safe_test_target(None, "postgresql+psycopg://somehost:notaport/gainmiles_test")
    assert_safe_message(str(excinfo.value))


def test_guard_rejects_unparsable_url() -> None:
    with pytest.raises(UnsafeTestTarget) as excinfo:
        assert_safe_test_target(None, "this is not a url")
    assert_safe_message(str(excinfo.value))


def test_guard_rejects_non_postgres_scheme() -> None:
    url = URL.create(
        drivername="mysql+pymysql",
        username=secrets.token_urlsafe(6),
        password=rand_password(),
        host="localhost",
        port=3306,
        database="gainmiles_test",
    ).render_as_string(hide_password=False)
    with pytest.raises(UnsafeTestTarget) as excinfo:
        assert_safe_test_target(None, url)
    assert_safe_message(str(excinfo.value))


def test_guard_rejects_url_without_host() -> None:
    url = pg_url(host=None, port=None, database="gainmiles_test")
    with pytest.raises(UnsafeTestTarget) as excinfo:
        assert_safe_test_target(None, url)
    assert_safe_message(str(excinfo.value))


@pytest.mark.parametrize("key", ["host", "hostaddr", "port", "dbname", "database"])
def test_guard_rejects_query_parameter_override(key: str) -> None:
    url = pg_url(database="gainmiles_test", query={key: "override"})
    with pytest.raises(UnsafeTestTarget) as excinfo:
        assert_safe_test_target(None, url)
    assert_safe_message(str(excinfo.value))


# --- models -----------------------------------------------------------------


def test_models_register_six_tables_without_a_database() -> None:
    # Importing the models must not require DATABASE_URL (lazy engine).
    from app import db  # noqa: F401
    import app.models  # noqa: F401

    assert set(db.Base.metadata.tables) == {
        "products",
        "categories",
        "sizes",
        "colors",
        "product_sizes",
        "product_colors",
    }


# --- setup_env: rendering ---------------------------------------------------


def test_env_example_only_has_placeholder_secrets() -> None:
    text = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    assert "POSTGRES_PASSWORD=change-me" in text
    assert "DATABASE_URL=postgresql+psycopg://gainmiles:change-me@" in text
    assert "TEST_DATABASE_URL=postgresql+psycopg://gainmiles:change-me@" in text


def test_render_env_encodes_password_and_aligns_urls() -> None:
    example = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    # A dynamic value that exercises the characters that must be percent-encoded.
    password = (
        secrets.token_urlsafe(8)
        + "@"
        + secrets.token_urlsafe(6)
        + ":/+"
        + secrets.token_urlsafe(6)
    )
    rendered = setup_env.render_env(example, password)
    values = {
        line.split("=", 1)[0]: line.split("=", 1)[1]
        for line in rendered.splitlines()
        if line and not line.startswith("#") and "=" in line
    }
    assert values["POSTGRES_PASSWORD"] == password
    assert quote(password, safe="") in values["DATABASE_URL"]
    assert values["DATABASE_URL"].endswith(":55432/gainmiles")
    assert values["TEST_DATABASE_URL"].endswith(":55433/gainmiles_test")


# --- setup_env: exclusive, secure creation ----------------------------------


def test_write_env_refuses_overwrite_and_sets_private_mode(tmp_path: Path) -> None:
    example = make_example(tmp_path)
    env = tmp_path / ".env"
    password = rand_password()

    assert setup_env.write_env(example, env, password=password) is True
    created = env.read_bytes()
    assert env.stat().st_mode & 0o777 == 0o600
    assert password in created.decode("utf-8")

    # A second run must not overwrite the existing .env.
    assert setup_env.write_env(example, env, password=rand_password()) is False
    assert env.read_bytes() == created


def test_write_env_refuses_existing_symlink(tmp_path: Path) -> None:
    example = make_example(tmp_path)
    real = tmp_path / "real.env"
    real.write_text("ORIGINAL", encoding="utf-8")
    env = tmp_path / ".env"
    env.symlink_to(real)

    assert setup_env.write_env(example, env, password=rand_password()) is False
    assert env.is_symlink()
    assert real.read_text(encoding="utf-8") == "ORIGINAL"


def test_write_env_is_exclusive_under_race(tmp_path: Path) -> None:
    example = make_example(tmp_path)
    env = tmp_path / ".env"
    password = rand_password()
    barrier = threading.Barrier(2)

    def attempt() -> bool:
        barrier.wait()
        return setup_env.write_env(example, env, password=password)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [future.result() for future in [pool.submit(attempt), pool.submit(attempt)]]

    assert sorted(results) == [False, True]
    assert password in env.read_text(encoding="utf-8")


# --- alembic URL escaping ---------------------------------------------------


def test_alembic_url_is_percent_escaped_roundtrip() -> None:
    from alembic.config import Config

    from conftest import escape_config_value

    url = pg_url(password="a%" + secrets.token_urlsafe(8), database="gainmiles_test")
    assert "%" in url  # the URL genuinely contains a character that needs escaping

    config = Config()
    config.set_main_option("sqlalchemy.url", escape_config_value(url))
    assert config.get_main_option("sqlalchemy.url") == url


# --- compose configuration consistency --------------------------------------


def _healthcheck_env_references(service: dict) -> set[str]:
    """POSTGRES_* variables referenced by a service healthcheck command."""
    healthcheck = service.get("healthcheck") or {}
    command = healthcheck.get("test")
    if not command:
        return set()
    text = " ".join(command) if isinstance(command, list) else str(command)
    return {
        name for name in _ENV_REFERENCE.findall(text) if name.startswith("POSTGRES_")
    }


def _service_environment_keys(service: dict) -> set[str]:
    """Keys declared in a service's ``environment`` block."""
    environment = service.get("environment") or {}
    if isinstance(environment, dict):
        return set(environment)
    return {entry.split("=", 1)[0] for entry in environment}


def _undefined_healthcheck_env(compose: dict) -> dict[str, set[str]]:
    """Report services whose healthcheck uses POSTGRES_* vars they don't define.

    These variables are expanded by the container shell, so they must exist in
    that same service's ``environment``. Comparing names (not interpolated
    values) keeps this meaningful without needing a Docker daemon and without
    reading or printing any expanded credential.
    """
    problems: dict[str, set[str]] = {}
    for name, service in (compose.get("services") or {}).items():
        missing = _healthcheck_env_references(service) - _service_environment_keys(service)
        if missing:
            problems[name] = missing
    return problems


def test_compose_healthchecks_only_reference_defined_service_env() -> None:
    compose = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    problems = _undefined_healthcheck_env(compose)
    assert problems == {}, f"healthchecks reference undefined env vars: {problems}"


def test_healthcheck_env_consistency_checker_flags_old_variable() -> None:
    # Regression: the pre-fix db_test healthcheck used ${POSTGRES_TEST_DB}, which
    # is not part of the container environment (only POSTGRES_USER / _PASSWORD /
    # _DB are). The checker must flag it.
    buggy = {
        "services": {
            "db_test": {
                "environment": {
                    "POSTGRES_USER": "gainmiles",
                    "POSTGRES_PASSWORD": "<generated>",
                    "POSTGRES_DB": "gainmiles_test",
                },
                "healthcheck": {
                    "test": [
                        "CMD-SHELL",
                        "pg_isready -U $${POSTGRES_USER} -d $${POSTGRES_TEST_DB}",
                    ]
                },
            }
        }
    }
    assert _undefined_healthcheck_env(buggy) == {"db_test": {"POSTGRES_TEST_DB"}}


def test_compose_db_healthchecks_target_their_own_database() -> None:
    # Beyond consistency: each database service must check the database it
    # actually creates, via the container-expanded POSTGRES_DB.
    compose = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    for name in ("db", "db_test"):
        service = compose["services"][name]
        text = " ".join(service["healthcheck"]["test"])
        assert "pg_isready" in text
        assert "POSTGRES_DB" in _healthcheck_env_references(service)
