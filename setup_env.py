#!/usr/bin/env python3
"""Create the local ``.env`` file from ``.env.example``.

Only the standard library is used, so this runs with any Python 3 without the
project virtual environment. The script:

* generates a random database password (never printed),
* URL-encodes the password before embedding it in the connection URLs,
* keeps ``POSTGRES_*`` values, host ports and both connection URLs aligned,
* refuses to overwrite an existing ``.env`` file.

It intentionally never prints the password or the full connection URLs.
"""

from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path
from urllib.parse import quote

PROJECT_ROOT = Path(__file__).resolve().parent
EXAMPLE_PATH = PROJECT_ROOT / ".env.example"
ENV_PATH = PROJECT_ROOT / ".env"

# Keys copied from .env.example (or from DEFAULTS when absent).
CONFIG_KEYS = (
    "POSTGRES_USER",
    "POSTGRES_DB",
    "POSTGRES_TEST_DB",
    "DB_HOST_PORT",
    "DB_TEST_HOST_PORT",
)
# Every key the generated .env must contain, in a stable order.
KNOWN_KEYS = (
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_DB",
    "POSTGRES_TEST_DB",
    "DB_HOST_PORT",
    "DB_TEST_HOST_PORT",
    "DATABASE_URL",
    "TEST_DATABASE_URL",
)

DEFAULTS = {
    "POSTGRES_USER": "gainmiles",
    "POSTGRES_DB": "gainmiles",
    "POSTGRES_TEST_DB": "gainmiles_test",
    "DB_HOST_PORT": "55432",
    "DB_TEST_HOST_PORT": "55433",
}


def _key_of(line: str) -> str | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None
    return stripped.partition("=")[0].strip()


def _parse_example(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        key = _key_of(line)
        if key is not None:
            values[key] = line.strip().partition("=")[2].strip()
    return values


def _generate_password() -> str:
    return secrets.token_urlsafe(24)


def render_env(example_text: str, password: str) -> str:
    """Return the ``.env`` content based on the example, with secrets filled in."""
    example_values = _parse_example(example_text)
    config = dict(DEFAULTS)
    for key in CONFIG_KEYS:
        if example_values.get(key):
            config[key] = example_values[key]

    user = config["POSTGRES_USER"]
    encoded = quote(password, safe="")
    replacements = {
        "POSTGRES_PASSWORD": password,
        "DATABASE_URL": (
            f"postgresql+psycopg://{user}:{encoded}"
            f"@localhost:{config['DB_HOST_PORT']}/{config['POSTGRES_DB']}"
        ),
        "TEST_DATABASE_URL": (
            f"postgresql+psycopg://{user}:{encoded}"
            f"@localhost:{config['DB_TEST_HOST_PORT']}/{config['POSTGRES_TEST_DB']}"
        ),
    }

    out_lines: list[str] = []
    seen: set[str] = set()
    for line in example_text.splitlines():
        key = _key_of(line)
        if key is None:
            out_lines.append(line)
            continue
        seen.add(key)
        if key in replacements:
            out_lines.append(f"{key}={replacements[key]}")
        elif key in config:
            out_lines.append(f"{key}={config[key]}")
        else:
            out_lines.append(line)

    # Guarantee every required key exists even if .env.example changes.
    for key in KNOWN_KEYS:
        if key not in seen:
            out_lines.append(f"{key}={replacements.get(key, config.get(key, ''))}")

    return "\n".join(out_lines).rstrip("\n") + "\n"


def write_env(
    example_path: Path,
    env_path: Path,
    *,
    password: str | None = None,
) -> bool:
    """Create ``env_path`` from ``example_path``, exclusively.

    The file is opened with ``O_CREAT | O_EXCL`` so an existing file (or a
    symlink) is never followed or replaced, and it is created with mode ``0600``
    from the start. There is deliberately no way to overwrite an existing file.

    Returns ``True`` when a new file was created, ``False`` when the target
    already exists or could not be created exclusively.
    """
    content = render_env(
        example_path.read_text(encoding="utf-8"), password or _generate_password()
    )

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(env_path, flags, 0o600)
    except OSError:
        # EEXIST means the path (including a symlink) already exists; any other
        # OS error means we cannot safely create the file. Either way: refuse.
        return False

    try:
        # Guarantee exactly 0600 even if a restrictive umask trimmed the mode.
        # The file is never more permissive than 0600 at any point.
        os.fchmod(fd, 0o600)
    except OSError:
        os.close(fd)
        raise
    try:
        handle = os.fdopen(fd, "w", encoding="utf-8")
    except BaseException:
        os.close(fd)
        raise
    with handle:
        handle.write(content)
    return True


def main() -> int:
    if not EXAMPLE_PATH.exists():
        print(f"error: {EXAMPLE_PATH.name} not found", file=sys.stderr)
        return 2
    if not write_env(EXAMPLE_PATH, ENV_PATH):
        print("error: .env already exists; refusing to overwrite", file=sys.stderr)
        return 1
    print("created .env with a random database password (value not shown)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
