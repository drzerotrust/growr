"""Discovery workflows; HTTP access belongs to integrations."""

from growr_cli.integrations.stonks import (
    STONKS_CATEGORIES as STONKS_CATEGORIES,
)
from growr_cli.searchers.dexscreener import (
    DexscreenerTokenSearcher as DexscreenerTokenSearcher,
)
from growr_cli.searchers.stonks import StonksSearcher as StonksSearcher

DexScrennerTokenSearcher = DexscreenerTokenSearcher
