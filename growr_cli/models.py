"""Small data containers used by the scanners.

These are deliberately plain. A CLI does not need an inheritance forest
to ask whether a mint authority is still alive.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Severity = Literal["critical", "high", "medium", "low", "info"]
CoverageStatus = Literal[
    "success", "failed", "partial", "no_data", "not_configured", "skipped"
]


@dataclass
class Finding:
    """One thing worth showing to a human.

    Attributes:
        severity: Triage level for the finding.
        label: Short title shown in the terminal.
        detail: One-line explanation of the finding.
        source: Where the fact came from, such as on-chain RPC.
    """

    severity: Severity
    label: str
    detail: str
    source: str


@dataclass
class ProviderStatus:
    """Provider coverage and a compact response summary.

    Attributes:
        provider: Provider name, such as Jupiter or Rugcheck.
        status: Coverage outcome for this scan.
        detail: Short explanation of success or failure.
        operation: Endpoint or workflow covered by this outcome.
    """

    provider: str
    status: CoverageStatus
    detail: str
    operation: str = "token_context"


@dataclass
class ScanReport:
    """A JSON-friendly report returned by every scan mode.

    Attributes:
        scan_type: Token, token_account, wallet, history or transaction.
        address: Requested address or transaction signature.
        rpc: Human-readable RPC label, never a secret-bearing URL.
        timestamp: UTC timestamp when the report was created.
        summary: Compact facts for the terminal and JSON output.
        findings: Operator-facing issues discovered during the scan.
        providers: Optional HTTP provider coverage records.
    """

    scan_type: str
    address: str
    rpc: str
    timestamp: str
    summary: dict[str, Any] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)
    providers: list[ProviderStatus] = field(default_factory=list)
    provider_data: dict[str, Any] = field(default_factory=dict, repr=False)
    social: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert nested dataclasses into normal JSON data.

        Returns:
            A plain dictionary suitable for ``json.dumps``.
        """

        data = asdict(self)
        data.pop("provider_data")
        return data


@dataclass
class TokenSearches:
    """JSON-friendly token searches list

    Attributes:
    tokens: Token records or the original Stonks response envelope.
    timestamp: Unix timestamp from when the search was performed.
    source: Discovery provider name. status: status of the search.
    """

    tokens: list[dict[str, Any]] | dict[str, Any]
    timestamp: float
    source: str
    status: str


@dataclass
class EnrichmentResult:
    """One provider's data and coverage for a single mint."""

    status: CoverageStatus
    fetched_at: str | None
    data: dict[str, Any] | list[dict[str, Any]] | None = None
    detail: str = ""


@dataclass
class SearchReport:
    """Discovery results and their provider-specific search mode."""

    search_type: str
    findings: TokenSearches

    def __post_init__(self) -> None:
        """Retain the untouched discovery response before enrichment."""

        self.raw = deepcopy(self.findings.tokens)

    def to_dict(self) -> dict[str, Any]:
        """Convert nested dataclasses into normal JSON data.

        Returns:
            A plain dictionary suitable for ``json.dumps``.
        """

        return asdict(self)


@dataclass
class ActivitySnapshot:
    """Normalized volumes and preserved provider interval fields."""

    values: dict[str, Any]
    buy_volume: Any = None
    sell_volume: Any = None


@dataclass
class ProviderSnapshot:
    """Normalized measurements separate from raw provider records."""

    source: str
    market: dict[str, Any]
    risk: dict[str, Any]
    activity: dict[str, ActivitySnapshot] = field(default_factory=dict)
