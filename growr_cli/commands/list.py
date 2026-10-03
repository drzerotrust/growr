"""Run Jupiter and Stonks token listings."""

from functools import partial

from growr_cli import settings
from growr_cli.enrichment import LaunchEnricher
from growr_cli.enrichment.on_chain import OnChainEnricher
from growr_cli.enrichment.token_context import TokenContext
from growr_cli.integrations.jupiter import JupiterClient
from growr_cli.integrations.rugcheck import RugcheckClient
from growr_cli.integrations.stonks import StonksClient
from growr_cli.models import ScanReport
from growr_cli.scanners import TokenScanner
from growr_cli.searchers import JupiterTokenSearcher, StonksSearcher
from growr_cli.solana.rpc import SolanaRpcClient


def list_tokens(
    args,
    rpc_url,
    rpc_label,
    http,
    rpc_client=None,
    token_scanner=None,
    jupiter_client=None,
    rugcheck_client=None,
    jupiter_searcher=None,
    stonks_client=None,
    stonks_searcher=None,
    launch_enricher=None,
    on_chain_enricher=None,
):
    """Run a token listing and optional RPC verification."""

    rpc_client = rpc_client or SolanaRpcClient
    token_scanner = token_scanner or TokenScanner
    jupiter_client = jupiter_client or JupiterClient
    rugcheck_client = rugcheck_client or RugcheckClient
    jupiter_searcher = jupiter_searcher or JupiterTokenSearcher
    stonks_client = stonks_client or StonksClient
    stonks_searcher = stonks_searcher or StonksSearcher
    launch_enricher = launch_enricher or LaunchEnricher
    on_chain_enricher = on_chain_enricher or OnChainEnricher
    jupiter = jupiter_client(http, settings.JUPITER_API_KEY)
    context = TokenContext(jupiter, rugcheck_client(http))

    if not args.stonk:
        report = jupiter_searcher(jupiter).search(
            args.jupiter_search,
            interval=args.interval,
            limit=args.limit,
        )
        if not args.on_chain:
            return report

        scan_function = partial(
            scan_listed_token,
            args=args,
            rpc_url=rpc_url,
            rpc_label=rpc_label,
            http=http,
            context=context,
            rpc_client=rpc_client,
            token_scanner=token_scanner,
        )
        return on_chain_enricher(scan_function).enrich(report)

    report = stonks_searcher(stonks_client(http)).search(
        args.stonk_search,
        page=args.page or 1,
        page_size=args.page_size or 30,
        category=args.category,
    )
    if not args.on_chain:
        return launch_enricher(jupiter, None).enrich(report)

    scan_function = partial(
        scan_listed_token,
        args=args,
        rpc_url=rpc_url,
        rpc_label=rpc_label,
        http=http,
        context=context,
        rpc_client=rpc_client,
        token_scanner=token_scanner,
    )
    return launch_enricher(jupiter, scan_function).enrich(report)


def scan_listed_token(
    mint,
    args,
    rpc_url,
    rpc_label,
    http,
    context,
    rpc_client,
    token_scanner,
) -> ScanReport:
    """Scan one listed mint with a short-lived RPC client."""

    launch_rpc = rpc_client(
        rpc_url,
        settings.REQUEST_TIMEOUT_SECONDS,
        commitment=args.commitment,
        budget=http.budget,
    )
    try:
        return token_scanner(launch_rpc, rpc_label, context).scan(
            mint,
            include_jupiter=False,
            include_rugcheck=False,
            include_market_context=False,
        )
    finally:
        launch_rpc.close()
