"""Offline compatibility information for installed skill consumers."""

import argparse
import json
from importlib.util import find_spec
from typing import Any

from growr_cli import __version__, settings
from growr_cli.playbook_commands import PLAYBOOKS

CONTRACTS = {"cli": "2.2", "playbook": "1.1", "screening": "1.0"}


def version_parts(value) -> tuple[int, ...]:
    """Accept three numeric release components for version bounds."""

    pieces = value.split(".")
    if len(pieces) != 3 or not all(
        piece.isascii() and piece.isdigit() and len(piece) <= 6
        for piece in pieces
    ):
        raise argparse.ArgumentTypeError("use a release such as 0.3.0")
    return tuple(int(piece) for piece in pieces)


def add_doctor_parser(subparsers) -> None:
    """Register offline compatibility constraints and JSON output."""

    parser = subparsers.add_parser(
        "doctor",
        help="Check local installation and required JSON contracts offline.",
        description="Check Growr version, packaged playbooks and JSON "
        "contracts. No network calls or credential values are emitted.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Examples:\n  growr doctor --json\n"
        "  growr doctor --min-version 0.3.0 --max-version 0.4.0 "
        "--require-cli-schema 2.2 --require-playbook-version 1.1 --json\n\n"
        "Minimum version is inclusive; maximum is exclusive. "
        "Success does not establish live provider availability.",
    )
    parser.add_argument(
        "--json", action="store_true", default=argparse.SUPPRESS
    )
    parser.add_argument("--min-version", type=version_parts)
    parser.add_argument("--max-version", type=version_parts)
    parser.add_argument("--require-cli-schema")
    parser.add_argument("--require-playbook-version")
    parser.add_argument("--require-screening-version")


def compatibility_errors(args) -> list[str]:
    """Fail required version or contract mismatches explicitly."""

    errors = []
    current = version_parts(__version__)
    if args.min_version and current < args.min_version:
        errors.append("growr_version_below_minimum")
    if args.max_version and current >= args.max_version:
        errors.append("growr_version_at_or_above_maximum")
    expected = {
        "cli": args.require_cli_schema,
        "playbook": args.require_playbook_version,
        "screening": args.require_screening_version,
    }
    for name, version in expected.items():
        if version is not None and version != CONTRACTS[name]:
            errors.append("%s_contract_mismatch" % name)
    return errors


def build_report(args) -> dict[str, Any]:
    """Describe local compatibility without exposing configuration."""

    errors = compatibility_errors(args)
    modules = {
        name: find_spec("growr_cli.playbooks.%s" % module) is not None
        for name, module in PLAYBOOKS.items()
    }
    if not all(modules.values()):
        errors.append("missing_playbook_modules")
    if settings.ENVIRONMENT_FILE["status"] == "invalid":
        errors.append("invalid_environment_file")
    return {
        "doctor_version": "1.0",
        "status": "error" if errors else "success",
        "growr_version": __version__,
        "contracts": dict(CONTRACTS),
        "playbooks": modules,
        "configuration": {
            "environment_file": dict(settings.ENVIRONMENT_FILE),
            "jupiter_key": key_state(settings.JUPITER_API_KEY),
            "helius_key": key_state(settings.HELIUS_API_KEY),
        },
        "errors": errors,
        "network_checked": False,
    }


def key_state(value) -> str:
    """Report presence, never credential values or endpoints."""

    if value in {"your_jupiter_api_key", "your_helius_api_key"}:
        return "placeholder"
    return "configured" if value else "unset"


def run_doctor(args) -> int:
    """Print one offline report; incompatible installations exit one."""

    report = build_report(args)
    if args.json:
        print(json.dumps(report, allow_nan=False, indent=2))
    else:
        print("growr %s | doctor | %s" % (__version__, report["status"]))
        for name, version in CONTRACTS.items():
            print("%s contract: %s" % (name, version))
        for error in report["errors"]:
            print("Issue: %s" % error)
        print("Offline check; provider connectivity was not tested.")
    return 1 if report["errors"] else 0
