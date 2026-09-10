"""Offline checks for the live harness's traffic limits."""

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest

from scripts import live_smoke
from tests.test_enrichment import MINT, OTHER, launch_report


def test_request_budget_stops_concurrent_sends_at_thirty():
    budget = live_smoke.RequestBudget()

    def reserve(index):
        try:
            assert 0 < budget.reserve() <= 10
            return True
        except live_smoke.BudgetExceeded:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(reserve, range(50)))
    assert sum(outcomes) == budget.count == 30


def test_request_budget_stops_before_send_after_deadline(monkeypatch):
    budget = live_smoke.RequestBudget()
    monkeypatch.setattr(live_smoke, "monotonic", lambda: budget.started + 120)
    with pytest.raises(live_smoke.BudgetExceeded):
        budget.reserve()
    assert budget.count == 0


def test_stonks_harness_limits_verification_if_server_ignores_page_size(
    monkeypatch,
):
    report = launch_report([{"mint": MINT}, {"mint": OTHER}])
    monkeypatch.setattr(
        live_smoke,
        "StonksSearcher",
        Mock(return_value=Mock(search=Mock(return_value=report))),
    )
    enricher = Mock(return_value=Mock(enrich=Mock(return_value=report)))
    monkeypatch.setattr(live_smoke, "LaunchEnricher", enricher)
    live_smoke.stonks_listing(Mock())
    supplied = enricher.return_value.enrich.call_args.args[0]
    assert supplied.findings.tokens["pools"] == [{"mint": MINT}]
    assert len(supplied.raw["pools"]) == 2
