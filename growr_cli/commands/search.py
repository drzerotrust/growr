"""Run provider token searches."""

from growr_cli import settings
from growr_cli.integrations.jupiter import JupiterClient
from growr_cli.integrations.stonks import StonksClient
from growr_cli.searchers import JupiterTokenSearcher, StonksSearcher


def search_tokens(
    args,
    http,
    jupiter_client=None,
    jupiter_searcher=None,
    stonks_client=None,
    stonks_searcher=None,
):
    """Search the provider selected by the parsed command arguments."""

    jupiter_client = jupiter_client or JupiterClient
    jupiter_searcher = jupiter_searcher or JupiterTokenSearcher
    stonks_client = stonks_client or StonksClient
    stonks_searcher = stonks_searcher or StonksSearcher

    if args.provider == "stonks":
        searcher = stonks_searcher(stonks_client(http))
        return searcher.search_query(
            args.query,
            sort=args.sort,
            page=args.page,
            page_size=args.page_size,
        )

    jupiter = jupiter_client(http, settings.JUPITER_API_KEY)
    return jupiter_searcher(jupiter).search(
        "search",
        query=args.query,
    )
