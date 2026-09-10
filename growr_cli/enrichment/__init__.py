"""Launch enrichment and legacy raw-record normalization helpers."""

from typing import Any

from growr_cli.analysis.market import (
    combine_activity,
    combine_metrics,
    select_launch_pair,
)
from growr_cli.analysis.metrics import mapping as mapping
from growr_cli.analysis.metrics import metric as metric
from growr_cli.analysis.metrics import number as number
from growr_cli.enrichment.launches import LaunchEnricher as LaunchEnricher
from growr_cli.integrations.dexscreener import pool_snapshot
from growr_cli.integrations.dexscreener import snapshot as dex_snapshot
from growr_cli.integrations.jupiter import snapshot as jupiter_snapshot
from growr_cli.integrations.stonks import snapshot as stonks_snapshot


def choose_pair(pairs, launch) -> dict[str, Any]:
    """Adapt legacy raw-pair calls to normalized selection."""

    selected = select_launch_pair(
        [pool_snapshot(pair) for pair in pairs],
        launch["mint"],
        launch.get("pool"),
    )
    return selected.raw if selected is not None else {}


def activity_metrics(jupiter, pair) -> dict[str, Any]:
    """Adapt legacy raw statistics to activity calculation."""

    return combine_activity(jupiter_snapshot(jupiter), dex_snapshot(pair))


def normalize(launch, jupiter, pair) -> dict[str, Any]:
    """Adapt legacy raw records to measurement composition."""

    return combine_metrics(
        stonks_snapshot(launch), jupiter_snapshot(jupiter), dex_snapshot(pair)
    )
