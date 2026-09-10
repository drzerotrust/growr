"""Regression checks for the draft interactive shell."""

from unittest.mock import Mock

import pytest

client = pytest.importorskip(
    "client", reason="The interactive client is local-only."
)


@pytest.mark.parametrize(
    ("entered", "expected"),
    [("2", (2, False)), ("abc", (0, True)), ("", (0, True))],
)
def test_menu_input_handles_nonnumeric_text(monkeypatch, entered, expected):
    shell = client.Client.__new__(client.Client)
    monkeypatch.setattr("builtins.input", lambda prompt: entered)

    assert shell.get_choice() == expected


def test_banner_without_animation_keeps_every_line(
    monkeypatch, capsys, tmp_path
):
    shell = client.Client.__new__(client.Client)
    sleep = Mock()
    monkeypatch.setattr(client.time, "sleep", sleep)
    monkeypatch.setattr(client, "BANNER_DIR", tmp_path)
    (tmp_path / "banner.txt").write_text("growr\nRead-only Solana analysis\n")

    shell.title(no_time_sleep=True)

    output = capsys.readouterr().out
    for line in (client.BANNER_DIR / "banner.txt").read_text().splitlines():
        assert line in output
    sleep.assert_not_called()


@pytest.mark.parametrize(
    ("method", "command"),
    [
        ("token_scan_menu", "growr.py token"),
        ("wallet_scan_menu", "growr.py wallet"),
        ("token_account_scan_menu", "growr.py token-account"),
        ("search_tokens_menu", "growr.py list"),
    ],
)
def test_draft_forms_direct_users_to_cli(method, command):
    shell = client.Client.__new__(client.Client)

    with pytest.raises(NotImplementedError, match=command):
        getattr(shell, method)()
