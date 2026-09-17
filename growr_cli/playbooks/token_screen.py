"""Screen Solana candidates using public JSON and bounded children."""

import json
import sys
from typing import Any

from growr_cli.playbooks.reporting import display
from growr_cli.playbooks.screen_inputs import read_json, saved_evidence
from growr_cli.playbooks.screen_options import build_parser, validate_options
from growr_cli.playbooks.screen_workflow import (
    ScreenSession,
    discover,
    explicit_mints,
    report_result,
    verify_candidates,
)
from growr_cli.playbooks.screening import validate_criteria


def investigate(options, criteria, saved=None, runner=None) -> dict[str, Any]:
    """Collect or replay evidence and evaluate requested criteria."""

    session = None if saved is not None else ScreenSession(options, runner)
    if saved is not None:
        evidence, mints, scope = saved
    elif options.mints:
        evidence, mints, scope = explicit_mints(options, criteria, session)
    else:
        evidence, mints, scope = discover(options, session)
    scope["candidates_available"] = len(mints)
    scope["candidate_limit"] = options.candidate_limit
    scope["candidates_omitted"] = max(0, len(mints) - options.candidate_limit)
    mints = mints[: options.candidate_limit]
    evidence = [
        row for row in evidence if row["record"]["identity"]["mint"] in mints
    ]
    if session is not None:
        verify_candidates(evidence, mints, criteria, session)
    return report_result(evidence, mints, criteria, scope, options, session)


def render(report) -> None:
    """Summarize decisions while directing audit consumers to JSON."""

    print("growr playbook | token_screen | %s" % report["status"])
    print(
        "Evaluated: %(evaluated)s; matches: %(matched)s; "
        "unknown: %(unknown)s; rejected: %(rejected)s" % report["counts"]
    )
    for index, candidate in enumerate(report["matches"], 1):
        print("%s. %s" % (index, candidate["mint"]))
        for row in candidate["ranking"]:
            print(
                "  %s: %s (%s)"
                % (
                    row["field"],
                    display(row["value"]),
                    row["direction"],
                )
            )
    print("Use --json for conditions, evidence, unknowns and request usage.")


def main(argv=None) -> int:
    """Validate inputs, then emit one bounded screening report."""

    arguments = sys.argv[1:] if argv is None else argv
    parser = build_parser()
    options = parser.parse_args(arguments)
    validate_options(parser, options, arguments)
    try:
        criteria = validate_criteria(read_json(options.criteria, 65536))
        saved = (
            saved_evidence(read_json(options.input)) if options.input else None
        )
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
        parser.error(
            "invalid criteria or saved evidence; check the documented contract"
        )
    report = investigate(options, criteria, saved)
    if options.json:
        print(json.dumps(report, allow_nan=False, indent=2))
    else:
        render(report)
    return 1 if report["status"] == "error" else 0


if __name__ == "__main__":
    raise SystemExit(main())
