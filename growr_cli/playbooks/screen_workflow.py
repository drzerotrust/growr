"""Bound live screening work and preserve replayable public evidence."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import partial
from time import monotonic
from typing import Any

from growr_cli.playbooks.evidence import measured_totals
from growr_cli.playbooks.runner import GrowrRunner
from growr_cli.playbooks.screen_inputs import (
    append_document,
    discovery_document,
    evidence_mints,
    token_document,
)
from growr_cli.playbooks.screen_observations import candidates_from_evidence
from growr_cli.playbooks.screen_options import discovery_command
from growr_cli.playbooks.screening import (
    RPC_FIELDS,
    evaluate,
    rank_key,
    requirements,
)


@dataclass
class ScreenSession:
    """Reserve conservative costs before starting child processes."""

    options: Any
    runner: Any = None
    gaps: list[str] = field(default_factory=list, init=False)
    evidence: list[dict[str, Any]] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        """Create a runner and an absolute child execution deadline."""

        self.runner = self.runner or GrowrRunner(self.options.timeout, 31)
        self.deadline = monotonic() + self.options.max_seconds
        self.reserved = {"rpc": 0, "http": 0}

    def call(self, command, validator, rpc=0, http=0):
        """Retain reservations when child request counts are unknown."""

        remaining = self.deadline - monotonic()
        if remaining <= 0:
            self.gaps.append("deadline_exhausted")
            return None
        for name, cost in (("rpc", rpc), ("http", http)):
            limit = getattr(self.options, "max_%s_calls" % name)
            if self.reserved[name] + cost > limit:
                self.gaps.append("%s_budget_exhausted" % name)
                return None
        self.reserved["rpc"] += rpc
        self.reserved["http"] += http
        # Discovery skips RPC; RPC children disable provider context.
        # Positive CLI caps are supplied even for unused transports.
        result = self.runner.capture(
            command,
            validator,
            max(1, rpc),
            max(1, http),
            min(self.options.timeout, remaining),
        )
        if result is None:
            self.gaps.append("child_failed")
        elif result["status"] == "partial":
            self.gaps.append("partial_child")
        return result

    def budget(self) -> dict[str, Any]:
        """Separate observed counters from conservative reservations."""

        return {
            "rpc_limit": self.options.max_rpc_calls,
            "http_limit": self.options.max_http_calls,
            "reserved_upper_bounds": self.reserved,
            "subprocesses_attempted": len(self.runner.scans),
            "measured": measured_totals(self.runner.scans),
        }


def discover(
    options, session
) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    """Read a bounded set of provider pages without on-chain fanout."""

    evidence = session.evidence
    pages = []
    stop = "page_limit"
    count = options.pages if options.provider == "stonks" else 1
    for page in range(options.page, options.page + count):
        command, expected = discovery_command(options, page)
        http = 2 if command[:2] == ["list", "stonks"] else 1
        document = session.call(
            command,
            partial(discovery_document, expected=(command[0], expected)),
            http=http,
        )
        if document is None:
            stop = "request_failed_or_bounded"
            break
        evidence = append_document(
            evidence, document, len(session.runner.scans) - 1
        )
        pages.append(
            {"request": expected, "pagination": document["pagination"]}
        )
        if len(evidence_mints(evidence)) >= options.candidate_limit:
            stop = "candidate_limit"
            break
        if not document["records"]:
            stop = "empty_provider_page"
            break
    mints = evidence_mints(evidence)
    return evidence, mints, {"pages": pages, "stop_reason": stop}


def explicit_mints(
    options, criteria, session
) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    """Retain supplied mints even when Jupiter metadata is missing."""

    mints = list(dict.fromkeys(options.mints))
    evidence = session.evidence
    fields = {
        row["field"] for row in requirements(criteria) + criteria["ranking"]
    }
    if fields - RPC_FIELDS:
        query = ",".join(mints)
        expected = {"source": "jupiter", "mode": "search", "query": query}
        document = session.call(
            ["search", "jupiter", query],
            partial(discovery_document, expected=("search", expected)),
            http=1,
        )
        if document is not None:
            if any(
                row["identity"]["mint"] not in mints
                for row in document["records"]
            ):
                session.gaps.append("unexpected_mint")
            else:
                evidence = append_document(
                    evidence, document, len(session.runner.scans) - 1
                )
    return evidence, mints, {"origin": "explicit_mints"}


def evaluated_candidates(
    evidence, mints, criteria, as_of
) -> list[dict[str, Any]]:
    """Recompute decisions from original observations."""

    return [
        evaluate(candidate, criteria, as_of)
        for candidate in candidates_from_evidence(evidence, mints, as_of)
    ]


def verify_candidates(evidence, mints, criteria, session) -> None:
    """Scan unresolved RPC criteria in preliminary ranking order."""

    as_of = datetime.now(timezone.utc)
    candidates = evaluated_candidates(evidence, mints, criteria, as_of)
    selected = sorted(
        (row for row in candidates if row["decision"] != "fail"),
        key=rank_key,
    )
    scans = 0
    for candidate in selected:
        fields = candidate["requirements"] + candidate["ranking"]
        needs_rpc = any(
            row["field"] in RPC_FIELDS and row["value"] is None
            for row in fields
        )
        if not needs_rpc:
            continue
        if scans >= session.options.scan_limit:
            session.gaps.append("scan_limit")
            break
        mint = candidate["mint"]
        count_before = len(session.runner.scans)
        document = session.call(
            ["token", mint, "--no-jupiter", "--no-rugcheck"],
            partial(token_document, mint=mint),
            rpc=4,
        )
        if len(session.runner.scans) == count_before:
            break
        scans += 1
        if document is not None:
            append_document(evidence, document, len(session.runner.scans) - 1)


def report_result(
    evidence, mints, criteria, scope, options, session=None
) -> dict[str, Any]:
    """Return matches, exclusions and evidence for offline replay."""

    as_of = datetime.now(timezone.utc)
    rows = evaluated_candidates(evidence, mints, criteria, as_of)
    matched = sorted(
        (row for row in rows if row["decision"] == "pass"), key=rank_key
    )
    unknown = sorted(
        (row for row in rows if row["decision"] == "unknown"), key=rank_key
    )
    rejected = sorted(
        (row for row in rows if row["decision"] == "fail"), key=rank_key
    )
    gaps = sorted(set(session.gaps)) if session else []
    if scope.get("source_status") == "partial":
        gaps.append("source_report_partial")
    partial_result = bool(
        gaps or unknown or any(not row["ranking_complete"] for row in matched)
    )
    status = "success" if rows else "no_data"
    if partial_result:
        status = "partial"
    if session and not evidence and session.gaps:
        status = "error"
    return {
        "playbook_version": "1.1",
        "playbook": "token_screen",
        "screening_version": "1.0",
        "status": status,
        "as_of": as_of.isoformat(),
        "criteria": criteria,
        "scope": {
            **scope,
            "selected_mints": mints,
            "offline": session is None,
            "limits": {
                name: getattr(options, name)
                for name in (
                    "candidate_limit",
                    "scan_limit",
                    "top",
                    "pages",
                    "page_size",
                    "timeout",
                    "max_seconds",
                    "max_rpc_calls",
                    "max_http_calls",
                )
            },
        },
        "counts": {
            "evaluated": len(rows),
            "matched": len(matched),
            "unknown": len(unknown),
            "rejected": len(rejected),
        },
        "matches": matched[: options.top],
        "other_matches": matched[options.top :],
        "unknown": unknown,
        "rejected": rejected,
        "gaps": gaps,
        "evidence": evidence,
        "scans": session.runner.scans if session else [],
        "budget": session.budget()
        if session
        else {
            "reserved_upper_bounds": {"rpc": 0, "http": 0},
            "subprocesses_attempted": 0,
            "measured": measured_totals([]),
        },
        "notes": [
            "Best matches within the stated discovery and verification scope.",
            "Ranking follows ordered criteria; missing values sort last. "
            "Exact mint breaks ties. No return prediction is calculated.",
            "Social presence does not verify authenticity. Largest accounts "
            "are not a census of distinct wallet owners.",
            "Provider time is used where exposed, otherwise retrieval time. "
            "Reads are not one slot. Saved evidence is not attested.",
        ],
    }
