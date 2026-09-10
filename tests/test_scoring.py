from unittest.mock import Mock

from growr_cli.models import Finding
from growr_cli.scanners import TokenScanner


def _scanner() -> TokenScanner:
    return TokenScanner(Mock(), "test RPC", Mock())


def test_severity_for_percentage() -> None:
    scanner = _scanner()
    assert scanner.severity_for_percentage(20) == "high"
    assert scanner.severity_for_percentage(10) == "medium"
    assert scanner.severity_for_percentage(9.99) == "low"


def test_score_findings_and_risk_band() -> None:
    scanner = _scanner()
    findings = [
        Finding("critical", "a", "a", "on-chain RPC"),
        Finding("high", "b", "b", "on-chain RPC"),
        Finding("info", "c", "c", "on-chain RPC"),
    ]

    score = scanner._score_findings(findings)
    assert score == 65
    assert scanner._risk_band(score) == "high"
    assert scanner._risk_band(19) == "low"
    assert scanner._risk_band(20) == "medium"
    assert scanner._risk_band(75) == "critical"


def test_score_is_capped_at_100() -> None:
    scanner = _scanner()
    findings = [
        Finding("critical", str(index), "x", "on-chain RPC")
        for index in range(5)
    ]
    assert scanner._score_findings(findings) == 100
