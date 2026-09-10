"""Pure mint findings, concentration thresholds, and risk scoring."""

from growr_cli.models import Finding, Severity


def severity_for_percentage(percentage) -> Severity:
    """Use intentionally boring thresholds for holder concentration.

    Args:
        percentage: Combined share of supply held by the largest
            accounts.

    Returns:
        A severity label for that concentration.
    """

    if percentage >= 20:
        return "high"
    if percentage >= 10:
        return "medium"
    return "low"


def mint_findings(mint) -> list[Finding]:
    """Convert chain facts into operator-facing findings."""

    findings = []
    if not mint["initialized"]:
        findings.append(
            Finding(
                "high",
                "Mint account uninitialized",
                "The mint account is not initialized. Authority bytes "
                "may be meaningless.",
                "on-chain RPC",
            )
        )
        return findings

    if mint["mint_authority"]:
        findings.append(
            Finding(
                "critical",
                "Mint authority enabled",
                "The mint authority still exists, so supply can be increased.",
                "on-chain RPC",
            )
        )
    else:
        findings.append(
            Finding(
                "info",
                "Mint authority disabled",
                "No active mint authority was found in the mint account.",
                "on-chain RPC",
            )
        )

    if mint["freeze_authority"]:
        findings.append(
            Finding(
                "high",
                "Freeze authority enabled",
                "The freeze authority can freeze token accounts.",
                "on-chain RPC",
            )
        )
    else:
        findings.append(
            Finding(
                "info",
                "Freeze authority disabled",
                "No active freeze authority was found in the mint account.",
                "on-chain RPC",
            )
        )

    if mint["token_program"] == "token_2022":
        findings.append(
            Finding(
                "medium",
                "Token-2022 mint",
                "This mint uses Token-2022. Review extensions before "
                "assuming standard SPL behavior.",
                "on-chain RPC",
            )
        )

    return findings


def holder_finding(holders) -> Finding:
    """Add a finding for the largest account concentration."""

    percentage = holders["top_twenty_percent"]
    severity = severity_for_percentage(percentage)
    return Finding(
        severity,
        "Top holder concentration",
        f"The largest reported token accounts hold {percentage:.2f}% "
        f"of supply.",
        "on-chain RPC",
    )


def score_findings(findings) -> int:
    """Calculate an explainable score for risk triage."""

    score = 0
    for finding in findings:
        if finding.severity == "critical":
            score += 40
        elif finding.severity == "high":
            score += 25
        elif finding.severity == "medium":
            score += 12
        elif finding.severity == "low":
            score += 5
    return min(score, 100)


def risk_band(score) -> str:
    """Translate a score into terminal-friendly language."""

    if score >= 75:
        return "critical"
    if score >= 45:
        return "high"
    if score >= 20:
        return "medium"
    return "low"
