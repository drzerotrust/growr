"""User configuration and database selection without real user files."""

from pathlib import Path

import pytest

from growr_cli.environment import database_file, environment_file


@pytest.fixture
def user_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("GROWR_ENV_FILE", raising=False)
    monkeypatch.delenv("GROWR_DATABASE_PATH", raising=False)
    return tmp_path


@pytest.mark.parametrize("config_root", [None, "", "~/settings"])
def test_user_environment_and_database_share_directory(
    user_home, monkeypatch, config_root
):
    if config_root is not None:
        monkeypatch.setenv("XDG_CONFIG_HOME", config_root)
    folder = user_home / ".config" / "growr"
    if config_root:
        folder = user_home / "settings" / "growr"

    assert database_file() == folder / "growr.db"
    assert not folder.exists()

    folder.mkdir(parents=True)
    config_file = folder / ".env"
    config_file.write_text("JUPITER_API_KEY=\n")
    assert environment_file(user_home / "installed") == (config_file, "user")
    assert not database_file().exists()


@pytest.mark.parametrize("override", ["~/custom/growr.db", "absolute"])
def test_database_override_wins_over_existing_files(
    user_home, monkeypatch, override
):
    for folder in [user_home / ".growr", user_home / ".config" / "growr"]:
        folder.mkdir(parents=True)
        (folder / "growr.db").touch()

    if override == "absolute":
        override = str(user_home / "custom" / "growr.db")
    monkeypatch.setenv("GROWR_DATABASE_PATH", override)

    assert database_file() == user_home / "custom" / "growr.db"
    assert not database_file().exists()


@pytest.mark.parametrize("override", ["", "   "])
def test_blank_database_override_uses_default(
    user_home, monkeypatch, override
):
    monkeypatch.setenv("GROWR_DATABASE_PATH", override)
    assert database_file() == user_home / ".config" / "growr" / "growr.db"


def test_existing_legacy_database_is_reused_without_moving(user_home):
    legacy = user_home / ".growr" / "growr.db"
    legacy.parent.mkdir()
    legacy.write_bytes(b"existing database")

    assert database_file() == legacy
    assert legacy.read_bytes() == b"existing database"
    assert not (user_home / ".config").exists()


def test_new_database_wins_when_both_locations_exist(user_home):
    legacy = user_home / ".growr" / "growr.db"
    legacy.parent.mkdir()
    legacy.touch()
    current = user_home / ".config" / "growr" / "growr.db"
    current.parent.mkdir(parents=True)
    current.touch()

    assert database_file() == current
    assert legacy.is_file()


def test_explicit_environment_location_does_not_relocate_database(
    user_home, monkeypatch
):
    config = user_home / "secrets" / "custom.env"
    monkeypatch.setenv("GROWR_ENV_FILE", str(config))

    assert environment_file(Path("installed")) == (config, "explicit")
    assert database_file() == user_home / ".config" / "growr" / "growr.db"
