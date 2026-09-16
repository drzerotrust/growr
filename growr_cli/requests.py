"""Thread-safe request budgets and observation receipts for one run."""

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Any


class RequestLimitError(ValueError):
    """A request was stopped before transport by the run budget."""


@dataclass
class RequestBudget:
    """Count reads without storing endpoints or credentials."""

    rpc_limit: int = 500
    http_limit: int = 100
    receipts: list[dict[str, Any]] = field(default_factory=list, init=False)
    lock: Any = field(default_factory=Lock, init=False, repr=False)
    blocked: dict[str, int] = field(
        default_factory=lambda: {"rpc": 0, "http": 0}, init=False
    )

    @property
    def limits(self) -> dict[str, int]:
        """Expose separately enforced RPC and provider limits."""

        return {"rpc": self.rpc_limit, "http": self.http_limit}

    def start(self, transport, operation, subject=None, commitment=None):
        """Reserve an attempt atomically before a worker sends it."""

        with self.lock:
            count = sum(
                item["transport"] == transport for item in self.receipts
            )
            if count >= self.limits[transport]:
                self.blocked[transport] += 1
                raise RequestLimitError(
                    "%s request budget exhausted" % transport
                )
            receipt = {
                "transport": transport,
                "operation": operation,
                "subject": subject,
                "commitment": commitment,
                "status": "pending",
                "slot": None,
                "retrieved_at": None,
            }
            self.receipts.append(receipt)
            return receipt

    def finish(self, receipt, status, slot=None, lamports=None) -> None:
        """Keep per-response slots; no shared snapshot is implied."""

        with self.lock:
            receipt.update(
                status=status,
                slot=slot if type(slot) is int else None,
                retrieved_at=datetime.now(timezone.utc).isoformat(),
            )
            if type(lamports) is int:
                receipt["lamports"] = str(lamports)

    def snapshot(self) -> dict[str, Any]:
        """Return attempts, failures and blocked reservations."""

        with self.lock:
            result = {}
            for transport in self.limits:
                items = [
                    row
                    for row in self.receipts
                    if row["transport"] == transport
                ]
                result[transport] = {
                    "limit": self.limits[transport],
                    "attempted": len(items),
                    "failed": sum(row["status"] == "failed" for row in items),
                    "blocked": self.blocked[transport],
                }
            return {**result, "observations": deepcopy(self.receipts)}
