#!/usr/bin/env python3
"""growr's read-only Python command-line scanner."""

from __future__ import annotations

import json
from contextlib import closing

from growr_cli import settings
from growr_cli.cli_parsers import _parse_arguments
from growr_cli.cli_parsers import build_parser as _build_parser
from growr_cli.cli_validators import validate_search_arguments, validate_target
from growr_cli.commands.good_call import run_good_call
from growr_cli.commands.list import list_tokens
from growr_cli.commands.search import search_tokens
from growr_cli.commands.snapshot import get_snapshot
from growr_cli.configuration import ConfigurationError, log_configuration
from growr_cli.doctor import run_doctor
from growr_cli.enrichment import LaunchEnricher as _LaunchEnricher
from growr_cli.enrichment.on_chain import OnChainEnricher as _OnChainEnricher
from growr_cli.enrichment.stonks_token import StonksTokenContext
from growr_cli.enrichment.token_context import TokenContext
from growr_cli.errors import _emit_failure, _log_error
from growr_cli.integrations.http import HttpClient, ProviderError
from growr_cli.integrations.jupiter import JupiterClient
from growr_cli.integrations.rugcheck import RugcheckClient
from growr_cli.integrations.stonks import StonksClient as _StonksClient
from growr_cli.integrations.stonks_token import StonksTokenClient
from growr_cli.logger import configure_console_logging, get_logger
from growr_cli.machine.response import Run, build_response, serialize
from growr_cli.machine.schema import response_schema
from growr_cli.output import renderer_for
from growr_cli.playbook_commands import run_playbook
from growr_cli.requests import RequestBudget
from growr_cli.safety import redact_endpoint
from growr_cli.scanners import (
    TokenAccountScanner,
    TokenScanner,
    WalletScanner,
)
from growr_cli.scanners.history import HistoryScanner
from growr_cli.searchers import JupiterTokenSearcher as _JupiterTokenSearcher
from growr_cli.searchers import StonksSearcher as _StonksSearcher
from growr_cli.solana.rpc import RpcError, SolanaRpcClient
from growr_cli.storage import SnapshotRepository

# Preserve parser helpers imported by older integrations.
build_parser = _build_parser
_validate_search_arguments = validate_search_arguments
_validate_target = validate_target

LOGGER = get_logger(__name__)

# Keep the legacy entry-point symbol available to callers.
StonksSearcher = _StonksSearcher
# Preserve names used by older test and integration helpers.
OnChainEnricher = _OnChainEnricher
StonksClient = _StonksClient
JupiterTokenSearcher = _JupiterTokenSearcher
LaunchEnricher = _LaunchEnricher


def _list_tokens(args, rpc_url, rpc_label, http):
    """Keep the listing helper available to older scripts."""

    return list_tokens(
        args,
        rpc_url,
        rpc_label,
        http,
        rpc_client=SolanaRpcClient,
        token_scanner=TokenScanner,
    )


def _build_report(args, rpc_url, rpc_label, http):
    """Execute discovery commands; scans remain in the entry point."""

    if args.scan_type == "search":
        return search_tokens(
            args,
            http,
            jupiter_client=JupiterClient,
            jupiter_searcher=JupiterTokenSearcher,
            stonks_client=StonksClient,
            stonks_searcher=StonksSearcher,
        )
    if args.scan_type == "list":
        return list_tokens(
            args,
            rpc_url,
            rpc_label,
            http,
            rpc_client=SolanaRpcClient,
            token_scanner=TokenScanner,
            jupiter_client=JupiterClient,
            rugcheck_client=RugcheckClient,
            jupiter_searcher=JupiterTokenSearcher,
            stonks_client=StonksClient,
            stonks_searcher=StonksSearcher,
            launch_enricher=LaunchEnricher,
            on_chain_enricher=OnChainEnricher,
        )

    LOGGER.info("Using %s", rpc_label)
    with closing(
        SolanaRpcClient(
            rpc_url,
            settings.REQUEST_TIMEOUT_SECONDS,
            commitment=args.commitment,
            budget=http.budget,
        )
    ) as rpc:
        if args.scan_type == "transaction":
            return HistoryScanner(rpc, rpc_label).transaction(args.signature)
        if args.scan_type == "history":
            return HistoryScanner(rpc, rpc_label).history(
                args.address, args.limit, args.before, args.until, args.details
            )
        if args.scan_type == "token":
            context = _token_context(args, http)
            return TokenScanner(rpc, rpc_label, context).scan(
                args.mint,
                include_jupiter=not args.no_jupiter,
                include_rugcheck=not args.no_rugcheck,
            )
        if args.scan_type == "wallet":
            return WalletScanner(rpc, rpc_label).scan(args.address)
        return TokenAccountScanner(rpc, rpc_label).scan(args.address)


def _token_context(args, http):
    """Create provider context for a direct token scan."""

    if args.stonk:
        return StonksTokenContext(
            StonksTokenClient(http), getattr(args, "reward_snapshot", None)
        )
    return TokenContext(
        JupiterClient(http, settings.JUPITER_API_KEY),
        RugcheckClient(http),
    )


def main() -> int:
    """Run a command with structured JSON failures when requested."""

    run = Run()
    args = _parse_arguments(run)

    if args is None:
        return 2

    if args.scan_type == "doctor":
        return run_doctor(args)

    if args.scan_type == "playbook":
        return run_playbook(args)

    if args.scan_type == "schema":
        print(json.dumps(response_schema(), allow_nan=False, indent=2))
        return 0

    if args.scan_type in {"snapshot", "good-call"}:
        return _run_database_command(args)

    configure_console_logging(
        use_color=not args.no_color,
        quiet=args.quiet,
        enabled=args.verbose or args.quiet,
    )

    rpc_url_override = args.rpc_url.strip() if args.rpc_url else None
    rpc_url = rpc_url_override or settings.RPC_URL
    rpc_label = (
        "CLI --rpc-url override" if rpc_url_override else settings.RPC_LABEL
    )

    LOGGER.info("Starting %s run", args.scan_type)
    with redact_endpoint(rpc_url):
        return _execute_run(args, run, rpc_url, rpc_label, rpc_url_override)


def _execute_run(args, run, rpc_url, rpc_label, rpc_url_override) -> int:
    """Execute and render within the private redaction context."""

    run.budget = RequestBudget(args.max_rpc_calls, args.max_http_calls)
    try:
        log_configuration(args, rpc_url, rpc_url_override)
        with closing(
            HttpClient(settings.REQUEST_TIMEOUT_SECONDS, run.budget)
        ) as http:
            report = _build_report(args, rpc_url, rpc_label, http)

        requests = run.budget.snapshot()
        LOGGER.info(
            "Requests attempted: %s RPC, %s provider HTTP",
            requests["rpc"]["attempted"],
            requests["http"]["attempted"],
        )

        response = _build_response_if_needed(args, run, report)
        _store_snapshot_if_requested(args, response)

        LOGGER.info("Rendering %s report", "JSON" if args.json else "console")
        if args.json:
            # Serialize fully before writing to stdout.
            assert response is not None
            print(serialize(response))
        else:
            renderer_for(report, use_color=not args.no_color).render(report)

    except ConfigurationError as error:
        _log_error(args, "Configuration failed: %s" % error, logger=LOGGER)
        if args.json:
            _emit_failure(run, args, "EXECUTION_FAILED", str(error))
        return 1
    except ProviderError as error:
        # Safe transport details retain API codes and Retry-After for
        # scheduled callers. Arbitrary ValueError text stays concealed.
        _log_error(args, "Run failed: %s" % error, logger=LOGGER)
        if args.json:
            _emit_failure(run, args, "EXECUTION_FAILED", str(error))
        return 1
    except (ValueError, RpcError) as error:
        code = (
            "RPC_ERROR" if isinstance(error, RpcError) else "EXECUTION_FAILED"
        )
        if args.json:
            message = (
                "RPC read failed"
                if code == "RPC_ERROR"
                else "Scan or discovery could not be completed"
            )
            _log_error(args, "Run failed: %s" % message, logger=LOGGER)
            _emit_failure(run, args, code, message)
        else:
            _log_error(args, "Run failed: %s" % error, logger=LOGGER)
        return 1
    except Exception as error:
        _log_error(
            args,
            "Run failed: unexpected error (%s)" % type(error).__name__,
            logger=LOGGER,
        )
        if args.json:
            _emit_failure(
                run,
                args,
                "INTERNAL_ERROR",
                "Unexpected execution failure",
            )
        return 1
    LOGGER.info("Run complete")
    return 0


def _run_database_command(args) -> int:
    """Execute a local command without creating network clients."""

    try:
        if args.scan_type == "snapshot":
            success, value = get_snapshot(args)
        else:
            success, value = run_good_call(args)
    except Exception:
        # Database paths and SQL errors are not suitable agent output.
        success = False
        value = "Database operation failed"

    result = {
        "command": args.scan_type,
        "status": "success" if success else "error",
    }
    if success:
        result["data"] = value
    else:
        result["error"] = value

    print(json.dumps(result, default=str, indent=None if args.json else 2))
    return 0 if success else 1


def _store_snapshot_if_requested(args, response) -> None:
    """Persist listing records when requested."""

    if response is None or not getattr(args, "store_snapshot", False):
        return
    receipt = SnapshotRepository().store_response(response)
    LOGGER.info(
        "Stored %s token snapshots in run %s",
        receipt["snapshots"],
        receipt["run_id"],
    )


def _build_response_if_needed(args, run, report):
    """Build machine output only for JSON or persistence requests."""

    if not (args.json or getattr(args, "store_snapshot", False)):
        return None
    return build_response(run, args, report)


if __name__ == "__main__":
    raise SystemExit(main())
