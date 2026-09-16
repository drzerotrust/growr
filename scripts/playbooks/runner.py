"""Run Growr as a child process and retain safe evidence receipts."""

import json
import math
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from solders.pubkey import Pubkey
from solders.signature import Signature

from scripts.playbooks.evidence import measured_requests, validate_activity

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def valid_address(value) -> bool:
    """Check a public key locally before scheduling a child command."""

    if not isinstance(value, str):
        return False
    try:
        Pubkey.from_string(value)
    except ValueError:
        return False
    return True


def reject_constant(value) -> None:
    """Reject non-finite JSON constants instead of accepting NaN."""

    raise ValueError("Non-finite JSON number")


def finite_number(value) -> float:
    """Reject numeric overflow in otherwise valid JSON numbers."""

    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Non-finite JSON number")
    return result


def validate_document(document) -> None:
    """Require the supported Growr envelope before reading evidence."""

    if not isinstance(document, dict):
        raise ValueError("Expected a Growr document")
    if (
        document.get("schema_version") != "2.2"
        or document.get("tool", {}).get("name") != "growr"
        or document.get("status") not in {"success", "partial", "no_data"}
        or document.get("error") is not None
    ):
        raise ValueError("Unsupported Growr document")


def scan_record(document, kind, address) -> dict[str, Any]:
    """Require the requested identity and supported public contract."""

    validate_document(document)
    if document["status"] == "no_data":
        raise ValueError("Expected scan facts")
    request = document["request"]
    if request["command"] != kind or request["target"] != address:
        raise ValueError("Growr request does not match the command")
    records = document["records"]
    if not isinstance(records, list) or len(records) != 1:
        raise ValueError("Expected one scan record")
    record = records[0]
    identity_key = "signature" if kind == "transaction" else "address"
    if (
        record["kind"] != kind
        or record["identity"][identity_key] != address
        or record["identity"]["chain"] != "solana"
        or not isinstance(record["facts"], dict)
        or record["facts"].get("source") != "rpc"
        or not isinstance(record["coverage"], list)
    ):
        raise ValueError("Growr record does not match the command")
    return record


def search_records(document, mints) -> list[dict[str, Any]]:
    """Accept only the requested exact-mint Jupiter search results."""

    validate_document(document)
    request = document["request"]
    options = request["options"]
    if (
        request["command"] != "search"
        or request["target"] is not None
        or request["rpc"] is not None
        or options.get("source") != "jupiter"
        or options.get("mode") != "search"
        or options.get("query") != ",".join(mints)
    ):
        raise ValueError("Growr search does not match the command")
    records = document["records"]
    if not isinstance(records, list) or not isinstance(
        document["coverage"], list
    ):
        raise ValueError("Invalid search records or coverage")
    seen = set()
    for record in records:
        mint = record["identity"]["mint"]
        if mint not in mints or mint in seen:
            raise ValueError("Unexpected or duplicate mint")
        validate_search_record(record)
        seen.add(mint)
    return records


def validate_search_record(record) -> None:
    """Keep provider metadata separate from RPC facts."""

    metrics = record["metrics"]["jupiter"]
    if (
        record["kind"] != "token_discovery"
        or record["identity"]["chain"] != "solana"
        or record["facts"]["source"] != "jupiter"
        or record["on_chain"] is not None
        or metrics["source"] != "jupiter"
        or metrics["scope"] != "token"
        or not isinstance(metrics["values"], dict)
        or not isinstance(record["social"], dict)
        or not isinstance(record["coverage"], list)
    ):
        raise ValueError("Invalid Jupiter record")


def scan_receipt(command) -> dict[str, Any]:
    """Create the public evidence receipt before starting a child."""

    return {
        "command": command,
        "status": "failed",
        "error": None,
        "returncode": None,
        "run": None,
        "coverage": [],
    }


@dataclass
class GrowrRunner:
    """Own sequential child commands with timeout and call limits."""

    timeout: int
    max_calls: int
    scans: list[dict[str, Any]] = field(default_factory=list, init=False)

    def history(self, address, limit=10, before=None) -> dict[str, Any] | None:
        """Read references; activity playbooks deduplicate bodies."""

        if not valid_address(address) or not 1 <= limit <= 100:
            raise ValueError("Invalid history request")
        command = ["history", address, "--limit", str(limit)]
        if before:
            Signature.from_string(before)
            command.extend(["--before", before])
        return self._execute(command)

    def transaction(self, signature) -> dict[str, Any] | None:
        """Read one transaction through the public CLI contract."""

        Signature.from_string(signature)
        return self._execute(["transaction", signature])

    def scan(self, kind, address) -> dict[str, Any] | None:
        """Capture JSON without forwarding child diagnostics."""

        if kind not in {"token", "wallet"} or not valid_address(address):
            raise ValueError("Invalid playbook command")
        command = [kind, address]
        if kind == "token":
            command.extend(["--no-jupiter", "--no-rugcheck"])
        return self._execute(command)

    def search(self, mints) -> list[dict[str, Any]] | None:
        """Fetch one batch of at most 100 distinct Solana mint IDs."""

        if (
            not 1 <= len(mints) <= 100
            or not all(valid_address(mint) for mint in mints)
            or len(set(mints)) != len(mints)
        ):
            raise ValueError("Invalid Jupiter mint batch")
        return self._execute(["search", "jupiter", ",".join(mints)])

    def _execute(self, command):
        """Enforce the shared subprocess budget and capture output."""

        if len(self.scans) >= self.max_calls:
            raise ValueError("Playbook subprocess budget exceeded")
        receipt = scan_receipt(command)
        self.scans.append(receipt)
        try:
            # An argument list avoids shell interpretation. The child
            # loads the root .env; endpoints never enter the receipts.
            result = subprocess.run(
                [
                    sys.executable,
                    str(PROJECT_ROOT / "growr.py"),
                    "--json",
                    "--no-color",
                    *command,
                ],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=self.timeout,
                check=False,
                shell=False,
            )
        except subprocess.TimeoutExpired:
            receipt["error"] = "child_timeout"
            return None
        except (OSError, UnicodeError):
            receipt["error"] = "child_execution_failed"
            return None
        receipt["returncode"] = result.returncode
        if result.returncode != 0:
            receipt["error"] = "growr_failed"
            return None
        return self._read_result(result.stdout, receipt, command)

    def _read_result(self, output, receipt, command):
        """Discard malformed output without exposing its contents."""

        try:
            document = json.loads(
                output,
                parse_constant=reject_constant,
                parse_float=finite_number,
            )
            evidence = (
                search_records(document, command[2].split(","))
                if command[0] == "search"
                else scan_record(document, *command[:2])
            )
            coverage = (
                evidence["coverage"]
                if isinstance(evidence, dict)
                else document["coverage"]
            )
            run = document["run"]
            if command[0] in {"history", "transaction"}:
                validate_activity(evidence, command, document["request"])
            requests = measured_requests(run)
            timing = {
                key: run[key] for key in ("id", "started_at", "completed_at")
            }
            if not all(isinstance(value, str) for value in timing.values()):
                raise ValueError("Invalid run timestamps")
        except (ValueError, KeyError, TypeError, AttributeError):
            receipt["error"] = "invalid_growr_output"
            return None
        receipt.update(
            status=document["status"],
            run=timing,
            coverage=coverage,
        )
        receipt["requests"] = requests
        return evidence
