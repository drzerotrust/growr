"""Launch enrichment and raw-record normalization helpers."""

from typing import Any

from growr_cli.analysis.market import combine_activity, combine_metrics
from growr_cli.analysis.metrics import mapping as mapping
from growr_cli.analysis.metrics import metric as metric
from growr_cli.analysis.metrics import number as number
from growr_cli.enrichment.launches import LaunchEnricher as LaunchEnricher
from growr_cli.integrations.jupiter import snapshot as jupiter_snapshot
from growr_cli.integrations.stonks import snapshot as stonks_snapshot


def activity_metrics(jupiter) -> dict[str, Any]:
    """Adapt provider statistics to activity calculation."""

    return combine_activity(jupiter_snapshot(jupiter))


def normalize(launch, jupiter) -> dict[str, Any]:
    """Compose Jupiter token metrics with Stonks discovery values."""

    return combine_metrics(stonks_snapshot(launch), jupiter_snapshot(jupiter))
