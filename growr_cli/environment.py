"""Select configuration independently of the installation location."""

import os
from io import StringIO
from pathlib import Path

from dotenv import load_dotenv
from dotenv.parser import parse_stream


def environment_file(project_root) -> tuple[Path | None, str]:
    """Prefer an explicit file, then checkout or user configuration."""

    explicit = os.environ.get("GROWR_ENV_FILE", "").strip()
    if explicit:
        return Path(explicit).expanduser().absolute(), "explicit"
    # Do not load shared credentials from installed site-packages.
    checkout = project_root / ".env"
    if (project_root / "pyproject.toml").is_file() and checkout.is_file():
        return checkout, "checkout"
    config_root = os.environ.get("XDG_CONFIG_HOME")
    folder = (
        Path(config_root).expanduser()
        if config_root
        else Path.home() / ".config"
    )
    config = folder / "growr" / ".env"
    return (config, "user") if config.is_file() else (None, "environment")


def load_environment(project_root) -> dict[str, str]:
    """Load one file without exposing its path or contents."""

    path, source = environment_file(project_root)
    state = {"source": source, "status": "not_selected"}
    if path is None:
        return state
    try:
        # Parse an in-memory stream so Unicode/IO errors are contained.
        # Validate first so dotenv cannot log malformed file text.
        text = path.read_text(encoding="utf-8")
        validate_environment(text)
    except (OSError, UnicodeError, ValueError):
        return {"source": source, "status": "invalid"}
    load_dotenv(stream=StringIO(text), override=False)
    # Children can use an absolute explicit path after changing cwd.
    if source == "explicit":
        os.environ["GROWR_ENV_FILE"] = str(path)
    return {"source": source, "status": "loaded"}


def validate_environment(text) -> None:
    """Reject malformed bindings before dotenv can log their text."""

    # Reject values the operating system cannot store before applying
    # bindings, so a bad file cannot leave configuration half loaded.
    if "\x00" in text:
        raise ValueError("Invalid environment file")
    for binding in parse_stream(StringIO(text)):
        if binding.error:
            raise ValueError("Invalid environment file")
        if binding.key is not None and (not binding.key or "=" in binding.key):
            raise ValueError("Invalid environment file")
