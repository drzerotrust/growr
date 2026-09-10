import pytest

from growr_cli.models import (
    Finding,
    ProviderStatus,
    ScanReport,
    SearchReport,
    TokenSearches,
)
from growr_cli.output import renderer_for
from growr_cli.renderers.base import BaseConsoleRenderer
from growr_cli.renderers.listings import (
    DexscreenerConsoleRenderer,
    ListConsoleRenderer,
)
from growr_cli.renderers.scans import (
    TokenAccountConsoleRenderer,
    TokenConsoleRenderer,
    WalletConsoleRenderer,
)
from growr_cli.renderers.stonkfun import StonkfunConsoleRenderer
from tests.test_enrichment import MINT, enricher, launch_report, providers_for


def _report() -> ScanReport:
    return ScanReport(
        scan_type="token",
        address="mint",
        rpc="test RPC",
        timestamp="2026-01-01T00:00:00+00:00",
        summary={
            "risk_score": 12,
            "holders": {"top_accounts": [{"owner": "x"}]},
        },
        findings=[
            Finding(
                "low",
                "Top holder concentration",
                "1.00% of supply.",
                "on-chain RPC",
            )
        ],
        providers=[
            ProviderStatus("Dexscreener", "success", "Market pair found")
        ],
    )


def test_no_color_skips_ansi(capsys) -> None:
    renderer = TokenConsoleRenderer(use_color=False)
    renderer.render(_report())
    output = capsys.readouterr().out

    assert "\033[" not in output
    assert "Top Holder Concentration" not in output or "Holders" in output
    assert "[LOW] Top holder concentration" in output
    assert "Dexscreener: SUCCESS" in output


@pytest.mark.parametrize(
    ("scan_type", "renderer_class", "title"),
    [
        ("token", TokenConsoleRenderer, "Token"),
        ("wallet", WalletConsoleRenderer, "Wallet"),
        ("token_account", TokenAccountConsoleRenderer, "Token Account"),
    ],
)
def test_scan_dispatch_and_shared_output(
    capsys, scan_type, renderer_class, title
):
    report = _report()
    report.scan_type = scan_type
    renderer = renderer_for(report, False)
    assert type(renderer) is renderer_class
    assert isinstance(renderer, BaseConsoleRenderer)
    renderer.render(report)
    text = capsys.readouterr().out
    assert f"growr | {title} Scan" in text
    assert "[LOW] Top holder concentration" in text
    assert "Dexscreener: SUCCESS" in text


@pytest.mark.parametrize(
    "mode", ["stonk-recent", "stonk-marketCap", "stonk-volume"]
)
def test_stonkfun_dispatch_keeps_tables(capsys, mode):
    report = launch_report()
    report.search_type = mode
    enricher(providers_for([MINT])).enrich(report)
    renderer = renderer_for(report, False)
    assert isinstance(renderer, StonkfunConsoleRenderer)
    assert isinstance(renderer, ListConsoleRenderer)
    assert isinstance(renderer, BaseConsoleRenderer)
    renderer.render(report)
    assert "Provider-reported risk" in capsys.readouterr().out


@pytest.mark.parametrize("mode", ["boosted", "community-takeovers"])
def test_dexscreener_listing_supports_table(capsys, mode):
    report = SearchReport(
        mode,
        TokenSearches([{"tokenAddress": MINT}], 0.0, "dexscreener", "success"),
    )
    renderer = renderer_for(report, False)
    assert type(renderer) is DexscreenerConsoleRenderer
    assert isinstance(renderer, ListConsoleRenderer)
    assert isinstance(renderer, BaseConsoleRenderer)
    renderer.render(report)
    output = capsys.readouterr().out
    assert MINT in output
    assert "Social" in output


def test_unknown_reports_fail_selection():
    report = _report()
    report.scan_type = "unknown"
    with pytest.raises(ValueError, match="No console renderer"):
        renderer_for(report, False)
    with pytest.raises(ValueError, match="No console renderer"):
        renderer_for(
            SearchReport(
                "unknown", TokenSearches([], 0.0, "unknown", "success")
            ),
            False,
        )


@pytest.mark.parametrize(
    "renderer_class",
    [
        TokenConsoleRenderer,
        WalletConsoleRenderer,
        TokenAccountConsoleRenderer,
        DexscreenerConsoleRenderer,
        StonkfunConsoleRenderer,
    ],
)
@pytest.mark.parametrize(
    ("tty", "requested", "expected"),
    [(False, True, False), (True, False, False), (True, True, True)],
)
def test_all_renderers_inherit_terminal_color_controls(
    monkeypatch, renderer_class, tty, requested, expected
):
    monkeypatch.setattr("sys.stdout.isatty", lambda: tty)
    assert renderer_class(requested).use_color is expected
