"""Run bounded, read-only smoke checks without printing payloads.

Uses the root .env through normal settings. Outbound requests are capped
at 30, socket timeouts at 10 seconds, and total time at 120 seconds.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
from contextlib import closing
from copy import deepcopy
from pathlib import Path
from threading import Lock
from time import monotonic
from typing import Any
from unittest.mock import patch

import httpx
import requests
from jsonschema import Draft202012Validator, FormatChecker

# Make the checked-out application importable when invoked as a script.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import growr
from growr_cli import settings
from growr_cli.configuration import log_configuration
from growr_cli.enrichment.launches import LaunchEnricher
from growr_cli.enrichment.on_chain import OnChainEnricher
from growr_cli.enrichment.token_context import TokenContext
from growr_cli.integrations.dexscreener import DexscreenerClient
from growr_cli.integrations.http import HttpClient
from growr_cli.integrations.jupiter import JupiterClient
from growr_cli.integrations.rugcheck import RugcheckClient
from growr_cli.integrations.stonks import StonksClient
from growr_cli.machine.response import Run, build_response, serialize
from growr_cli.machine.schema import response_schema
from growr_cli.safety import redact_endpoint
from growr_cli.scanners import TokenAccountScanner, TokenScanner, WalletScanner
from growr_cli.searchers import StonksSearcher
from growr_cli.solana.rpc import RpcError, SolanaRpcClient

MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


class BudgetExceeded(BaseException):
    """Stop validation across workflow error handlers."""


class RequestBudget:
    """Count outbound sends and redirects across worker threads."""

    def __init__(self, limit=30) -> None:
        """Keep request counts and deadline checks synchronized."""

        self.limit = limit
        self.started = monotonic()
        self.count = 0
        self.transport_errors = 0
        self.lock = Lock()

    def reserve(self) -> float:
        """Stop before sending beyond the request or time limit."""

        with self.lock:
            remaining = 120 - (monotonic() - self.started)
            if self.count >= self.limit or remaining <= 0:
                raise BudgetExceeded()
            self.count += 1
            return min(10, remaining)

    def failed_transport(self) -> None:
        """Count failures without retaining exception contents."""

        with self.lock:
            self.transport_errors += 1


def arguments(*command):
    """Use the same CLI argument validation as normal runs."""

    parser = growr.build_parser()
    args = parser.parse_args(["--json", *command])
    growr._validate_search_arguments(parser, args)
    growr._validate_target(parser, args)
    return args


def token_scan(http, mint, market=False):
    """Own RPC resources and optional direct-token providers."""

    context = TokenContext(
        JupiterClient(http, settings.JUPITER_API_KEY),
        DexscreenerClient(http),
        RugcheckClient(http),
    )
    with closing(SolanaRpcClient(settings.RPC_URL, 10)) as rpc:
        return TokenScanner(rpc, settings.RPC_LABEL, context).scan(
            mint, market, market, include_market_context=market
        )


def account_scan(kind, address):
    """Inspect a returned account or owner with the real scanner."""

    scanner = TokenAccountScanner if kind == "token-account" else WalletScanner
    with closing(SolanaRpcClient(settings.RPC_URL, 10)) as rpc:
        return scanner(rpc, settings.RPC_LABEL).scan(address)


def check(name, args, operation) -> tuple[Any, dict[str, Any]]:
    """Validate a report and return its safe outcome summary."""

    started = monotonic()
    run = Run()
    try:
        log_configuration(args, settings.RPC_URL, None)
        report = operation()
        document = json.loads(serialize(build_response(run, args, report)))
        Draft202012Validator(
            response_schema(), format_checker=FormatChecker()
        ).validate(document)
        outcome = {
            "check": name,
            "status": document["status"],
            "records": len(document["records"]),
            "coverage": [
                {key: item[key] for key in ("source", "operation", "status")}
                for item in document["coverage"]
            ],
            "elapsed_seconds": round(monotonic() - started, 2),
        }
        return report, outcome
    except Exception as error:
        outcome = {
            "check": name,
            "status": "error",
            "category": type(error).__name__,
        }
        if isinstance(error, RpcError):
            outcome["detail"] = str(error)
        return None, outcome


def record_check(results, name, args, operation):
    """Append a check while exposing its report to dependent checks."""

    report, outcome = check(name, args, operation)
    results.append(outcome)
    return report


def check_related_accounts(results, report) -> None:
    """Use public addresses returned by the token scan."""

    holders = (
        report.summary.get("holders", {}).get("top_accounts", [])
        if report
        else []
    )
    owner = next(
        (item["owner"] for item in holders if item.get("owner")), None
    )
    targets = (
        ("token-account", holders[0]["token_account"] if holders else None),
        ("wallet", owner),
    )
    for kind, address in targets:
        if not address:
            results.append({"check": kind, "status": "unverified"})
            continue
        record_check(
            results,
            kind,
            arguments(kind, address),
            lambda kind=kind, address=address: account_scan(kind, address),
        )


def stonks_listing(http):
    """Limit verification even if the provider ignores page size."""

    report = StonksSearcher(StonksClient(http)).search(
        "marketCap", page_size=1
    )
    envelope = report.findings.tokens
    if not isinstance(envelope, dict):
        raise ValueError("Expected a Stonks pool envelope")
    envelope["pools"] = envelope["pools"][:1]
    return LaunchEnricher(
        JupiterClient(http, settings.JUPITER_API_KEY),
        DexscreenerClient(http),
        lambda mint: token_scan(http, mint),
    ).enrich(report)


def check_listings(results, http) -> None:
    """Verify one Stonks pool and one Dexscreener Solana result."""

    args = arguments(
        "list",
        "stonks",
        "--stonk-search",
        "marketCap",
        "--page-size",
        "1",
        "--on-chain",
    )
    record_check(
        results, "stonks-on-chain", args, lambda: stonks_listing(http)
    )
    args = arguments("list", "dexscreener")
    report = record_check(
        results,
        "dexscreener",
        args,
        lambda: growr._search_tokens(
            args, settings.RPC_URL, settings.RPC_LABEL, http
        ),
    )
    eligible = (
        [
            item
            for item in report.findings.tokens
            if item.get("chainId") == "solana"
        ]
        if report
        else []
    )
    if not eligible:
        results.append(
            {"check": "dexscreener-on-chain", "status": "unverified"}
        )
        return
    # Limit verification in this harness without changing the CLI feed.
    report = deepcopy(report)
    report.findings.tokens = eligible[:1]
    args.on_chain = True
    record_check(
        results,
        "dexscreener-on-chain",
        args,
        lambda: OnChainEnricher(lambda mint: token_scan(http, mint)).enrich(
            report
        ),
    )


def main() -> int:
    """Enforce budgets and print only non-sensitive summaries."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mint", default=MINT, help="Mint for direct scan checks."
    )
    parser.add_argument(
        "--scans-only",
        action="store_true",
        help="Check the mint and returned owner/account only.",
    )
    parser.add_argument(
        "--max-requests",
        type=int,
        default=30,
        help="Lower the request cap (1 through 30).",
    )
    options = parser.parse_args()
    if not 1 <= options.max_requests <= 30:
        parser.error("--max-requests must be between 1 and 30")
    growr._validate_target(parser, arguments("token", options.mint))
    budget = RequestBudget(options.max_requests)
    results = []
    request_send = requests.Session.send
    rpc_send = httpx.Client.send

    def send_request(session, request, **kwargs):
        kwargs["timeout"] = budget.reserve()
        try:
            return request_send(session, request, **kwargs)
        except requests.RequestException:
            budget.failed_transport()
            raise

    def send_rpc(client, request, **kwargs):
        timeout = budget.reserve()
        request.extensions["timeout"] = dict.fromkeys(
            ("connect", "read", "write", "pool"), timeout
        )
        try:
            return rpc_send(client, request, **kwargs)
        except httpx.TransportError:
            budget.failed_transport()
            raise

    def deadline(signum, frame) -> None:
        # Exit immediately even if a thread is waiting on a slow peer.
        print(
            json.dumps(
                {"status": "deadline_exceeded", "requests": budget.count}
            ),
            flush=True,
        )
        os._exit(1)

    signal.signal(signal.SIGALRM, deadline)
    signal.alarm(120)
    try:
        with (
            patch.object(requests.Session, "send", send_request),
            patch.object(httpx.Client, "send", send_rpc),
            redact_endpoint(settings.RPC_URL),
            closing(HttpClient(10)) as http,
        ):
            report, outcome = check(
                "token",
                arguments("token", options.mint),
                lambda: token_scan(http, options.mint, True),
            )
            results.append(outcome)
            check_related_accounts(results, report)
            if not options.scans_only:
                check_listings(results, http)
    except BudgetExceeded:
        results.append({"check": "budget", "status": "exceeded"})
    finally:
        signal.alarm(0)
    print(
        json.dumps(
            {
                "requests": budget.count,
                "transport_errors": budget.transport_errors,
                "checks": results,
            },
            indent=2,
        )
    )
    return 0 if all(item["status"] == "success" for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
