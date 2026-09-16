"""Run envelopes, safe requests, and strict JSON serialization."""

import json
import math
from datetime import datetime, timezone
from time import perf_counter
from typing import Any
from uuid import uuid4

from growr_cli import __version__, settings
from growr_cli.machine.records import coverage, report_records
from growr_cli.machine.safety import safe_text
from growr_cli.requests import RequestBudget


class Run:
    """Capture timing once for either a report or an error."""

    def __init__(self) -> None:
        """Start a unique command invocation."""

        self.id = str(uuid4())
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.started_clock = perf_counter()
        self.budget = RequestBudget()

    def metadata(self) -> dict[str, Any]:
        """Finish timing with a monotonic duration and UTC timestamp."""

        return {
            "id": self.id,
            "started_at": self.started_at,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "elapsed_ms": max(
                0, round((perf_counter() - self.started_clock) * 1000, 3)
            ),
            "requests": self.budget.snapshot(),
        }


def request_metadata(args) -> dict[str, Any]:
    """Whitelist options without serializing argv or endpoints."""

    if args is None:
        return {"command": None, "target": None, "options": {}, "rpc": None}
    options = {"include_raw": args.include_raw}
    if args.scan_type == "search":
        options.update(source=args.provider, mode="search", query=args.query)
        if args.provider == "stonks":
            options.update(
                sort=args.sort, page=args.page, page_size=args.page_size
            )
    elif args.scan_type == "list":
        source = args.provider
        options["source"] = source
        options["mode"] = (
            args.stonk_search if args.stonk else args.jupiter_search
        )
        options["on_chain"] = args.on_chain
        if not args.stonk:
            options.update(interval=args.interval, limit=args.limit)
        if args.stonk:
            options.update(
                page=args.page or 1,
                page_size=args.page_size or 30,
                category=args.category,
            )
    elif args.scan_type == "token":
        options.update(
            jupiter=not (args.stonk or args.no_jupiter),
            rugcheck=not (args.stonk or args.no_rugcheck),
        )
        if args.stonk:
            options["stonk"] = True
            options["compare_rewards"] = args.compare_to is not None
    uses_rpc = args.scan_type not in {"list", "search"} or getattr(
        args, "on_chain", False
    )
    if uses_rpc:
        options["commitment"] = getattr(args, "commitment", "finalized")
    options.update(_history_options(args))
    rpc = "CLI --rpc-url override" if args.rpc_url else settings.RPC_LABEL
    return {
        "command": args.scan_type,
        "target": getattr(
            args,
            "signature",
            getattr(args, "mint", getattr(args, "address", None)),
        ),
        "options": options,
        "rpc": rpc if uses_rpc else None,
    }


def _history_options(args) -> dict[str, Any]:
    """Describe the exact requested address-history window."""

    if args.scan_type == "history":
        return {
            key: getattr(args, key)
            for key in ("limit", "before", "until", "details")
        }
    return {}


def _all_coverage(records) -> list[dict[str, Any]]:
    outcomes = []
    for record in records:
        outcomes.extend(record["coverage"])
        if record["on_chain"] is not None:
            outcomes.extend(_all_coverage([record["on_chain"]]))
    return outcomes


def _aggregate(outcomes) -> list[dict[str, Any]]:
    grouped = {}
    for item in outcomes:
        key = (item["source"], item["operation"])
        if key not in grouped:
            grouped[key] = [item]
        else:
            grouped[key].append(item)
    result = []
    priorities = {
        "success": 0,
        "skipped": 0,
        "no_data": 1,
        "not_configured": 2,
        "partial": 3,
        "failed": 4,
    }
    for (source, operation), items in grouped.items():
        worst = max(items, key=lambda item: priorities[item["status"]])
        timestamps = [item["fetched_at"] for item in items]
        fetched_at = max(timestamps) if all(timestamps) else None
        entry = coverage(
            source, operation, worst["status"], worst["detail"], fetched_at
        )
        entry["counts"] = {
            status: sum(item["status"] == status for item in items)
            for status in sorted({item["status"] for item in items})
        }
        result.append(entry)
    return result


def _skipped_providers(args) -> list[str]:
    """Expose context providers disabled by flags or Stonkfun mode."""

    if args.scan_type != "token":
        return []
    return [
        source
        for source in ("jupiter", "rugcheck")
        if args.stonk or getattr(args, "no_%s" % source, False)
    ]


def build_response(run, args=None, report=None, error=None) -> dict[str, Any]:
    """Normalize a run independently of console presentation."""

    records, pagination, outcomes = (
        report_records(report, args.include_raw)
        if report is not None
        else ([], None, [])
    )
    if args is not None and records:
        for source in _skipped_providers(args):
            records[0]["coverage"].append(
                coverage(
                    source,
                    "token_context",
                    "skipped",
                    "Disabled by request",
                )
            )
    outcomes.extend(_all_coverage(records))
    _exact_balances(records, run.budget.snapshot()["observations"])
    status = "success" if records else "no_data"
    if any(
        item["status"] in {"failed", "not_configured", "partial"}
        for item in outcomes
    ):
        status = "partial"
    result = {
        "schema_version": "2.2",
        "tool": {"name": "growr", "version": __version__},
        "run": run.metadata(),
        "request": request_metadata(args),
        "status": "error" if error else status,
        "records": records,
        "pagination": pagination,
        "coverage": _aggregate(outcomes),
        "error": error,
    }
    if report is not None and args.include_raw and hasattr(report, "raw"):
        result["raw"] = {"discovery": report.raw}
    return result


def _exact_balances(records, observations) -> None:
    """Attach exact lamports from measured RPC observations."""

    balances = {
        item["subject"]: item["lamports"]
        for item in observations
        if "lamports" in item and item["status"] == "success"
    }
    for item in records:
        if item["kind"] == "wallet":
            item["facts"]["sol_lamports"] = balances.get(
                item["identity"]["address"]
            )
        if item["kind"] == "token_account":
            owner = item["facts"].get("owner_wallet", {})
            owner["sol_lamports"] = balances.get(owner.get("address"))


def _clean(value, path="$") -> tuple[Any, list[dict[str, Any]]]:
    """Normalize non-finite numbers and reject unsupported values."""

    if isinstance(value, float) and not math.isfinite(value):
        return None, [
            coverage(
                "growr",
                "normalization",
                "partial",
                "Non-finite number replaced with null at %s" % path,
            )
        ]
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("JSON object keys must be strings")
        keys = [safe_text(key) for key in value]
        if len(set(keys)) != len(keys):
            raise TypeError("Redaction would merge JSON object keys")
        children = {
            key: _clean(item, "%s.%s" % (path, key))
            for key, item in zip(keys, value.values(), strict=True)
        }
        return (
            {key: child[0] for key, child in children.items()},
            [warning for child in children.values() for warning in child[1]],
        )
    if isinstance(value, list):
        entries = [
            _clean(item, "%s[%s]" % (path, index))
            for index, item in enumerate(value)
        ]
        return [entry[0] for entry in entries], [
            warning for entry in entries for warning in entry[1]
        ]
    if isinstance(value, str):
        return safe_text(value), []
    if value is None or isinstance(value, (int, float, bool)):
        return value, []
    raise TypeError("Unsupported value in machine output")


def serialize(document) -> str:
    """Prepare the entire document before writing any stdout bytes."""

    clean, warnings = _clean(document)
    if warnings:
        clean["coverage"].extend(warnings)
        if clean["status"] != "error":
            clean["status"] = "partial"
    return json.dumps(clean, allow_nan=False, ensure_ascii=True, indent=2)
