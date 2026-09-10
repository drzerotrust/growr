# growr

Read-only Solana research data for agents and automated reporting pipelines.
Use `--json` for a versioned evidence contract, or run without it for console
tables. growr retrieves observations and reports coverage; the consuming agent
handles scheduling, comparisons, selection, and narrative report generation.

It scans:

- token mints: authorities, standard Metaplex metadata, largest token accounts, Dexscreener market context, optional Rugcheck, and optional Jupiter enrichment
- SPL token accounts: mint, owner, balance, state, delegate, close authority, and basic owner-wallet context
- wallets: SOL balance, recent signature count, and SPL Token / Token-2022 account counts

The scanner does not sign, send, or simulate transactions, or persist analysis results.
It asks public/provider APIs and prints the answers. Run the CLI with
`python growr.py`.

## Requirements

- Python 3.10+
- A Solana mainnet RPC endpoint, optional but recommended for reliable results

Install the dependencies from the repository root:

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements.txt
```

## Environment

Configure `.env` in the repository root (next to `growr.py`) before running,
or deliberately use the built-in defaults shown in `.env.example`. Process
environment variables override `.env` values. Copy the included example and
add credentials for the services you want to enable. Never commit real keys.

```bash
cp .env.example .env
```

The example works unchanged: blank keys select public Solana RPC and leave
Jupiter enrichment unconfigured. No API key is required for basic RPC scans
or Dexscreener/Stonks discovery. Set `HELIUS_API_KEY` to select Helius and
`JUPITER_API_KEY` (or `JUP_API_KEY`) to enable Jupiter enrichment. Supply real
keys, not placeholder text. Custom RPC configuration is optional.

At startup, growr checks the settings needed by the selected command and
with `--verbose`, logs effective defaults, timeout, RPC selection, and key
presence to stderr. Console logging is disabled by default.
Custom URLs and keys are hidden completely. Invalid active URLs or copied
key placeholders stop the run before network calls, with exit code 1.
Missing optional keys remain visible as configuration/coverage information.
An invalid or non-finite timeout falls back to 15 seconds with a warning.
`--quiet` explicitly enables warning/error logs only; `--help` and `schema` run offline
without configuration validation. JSON stdout remains machine-readable.

`RUGCHECK_API_URL`, `DEXSCREENER_API_URL`, and `JUPITER_API_URL` configure
the provider API bases. They default to the values in `.env.example`.
`DEXSCREENER_API_URL` must include `/latest/dex` for single-token lookups;
`DEXSCREENER_V1_API_URL` uses the API root for discovery and batch lookups.
Using the root for both makes direct token enrichment fail even when
Dexscreener listings work.

The RPC selection order is explicit: `--rpc-url`, Helius when
`HELIUS_API_KEY` is set, `SOLANA_RPC_URL` (or the compatibility alias
`CUSTOM_RPC_URL`), then public Solana RPC.

When Helius is selected, the API key is placed in the RPC URL query string
(`?api-key=`). Reports only print a label such as `Helius RPC`, never the URL.
RPC errors retain the method, HTTP status, and error category. Response
bodies and arbitrary exception messages are omitted because they can contain
credentials. Output sanitization also covers the effective RPC override.
Do not put credential-bearing URLs directly in shell arguments. Use the environment
configuration for credentials and a safe RPC label in reports.

## Machine output contract

Version **1.0** replaces the pre-0.2 JSON format. Console tables remain the
default; `--json` selects the agent-facing format for every scan and listing.
Global flags precede the subcommand. There is no legacy JSON mode.

```bash
python growr.py --json token <MINT>
python growr.py --json list stonks --stonk-search volume
python growr.py --json --include-raw list stonks
python growr.py schema
```

`schema` prints a JSON Schema (Draft 2020-12) without network access. The schema
version is independent of growr's application version. Breaking contract changes
increment its major version; additive changes increment its minor version.
Consumers should check their supported schema version before reading records.

A JSON invocation writes exactly one document to stdout, including on handled
argument and execution errors. Human-readable `--help` remains help text.
Console logs are disabled by default, including on JSON failures. Enable them
with `--verbose`; logs then go to stderr. The document
is serialized before writing, so serialization errors produce an error envelope
instead of incomplete JSON. Broken pipes and externally terminated processes
cannot guarantee delivery of a document.

| Field | Meaning |
| --- | --- |
| `schema_version`, `tool` | Contract version and growr name/application version |
| `run` | Unique run ID, UTC start/completion times, elapsed milliseconds |
| `request` | Command, target, effective options and safe RPC label; no argv or credentials |
| `status` | `success`, `partial`, `no_data`, or `error` |
| `records` | Ordered array; one record for a direct scan, one per discovery result |
| `pagination` | Returned provider pagination, or `null` |
| `coverage` | Aggregated source/operation outcomes; counts are observations, not HTTP request counts |
| `error` | Stable error code and safe message, or `null` |
| `raw` | Optional original discovery envelope when `--include-raw` is enabled |

Records have `kind`, `identity`, `facts`, `metrics`, `findings`, `social`,
`coverage`, and `on_chain`. Kinds are `token`, `wallet`, `token_account`, `pool`,
and `token_discovery`. A mint can appear in multiple pool records; order and
identity preserve those separate markets. Discovery does not imply an RPC scan.

`facts` contains decoded account observations or named discovery metadata.
`metrics` separates provider measurements and growr-derived risk scoring.
Direct-scan provider sections contain `source`, `scope`, and `values`; Stonks
metrics retain their sourced market, activity and risk sections. `on_chain` is
an optional nested scan record. Social presence remains separate from risk.

Coverage entries contain `source`, `operation`, `status`, `detail`, and
`fetched_at`. Unknown retrieval times are `null`; run completion is not a proxy
for data freshness. Coverage statuses include `success`, `no_data`, `failed`,
`not_configured`, `partial`, and `skipped`. Explicitly disabled sources do not
make a report partial. Neither does a successful lookup without an indexed
record. Enabled-source failures, missing credentials, and incomplete reads do.

| Run outcome | Exit status |
| --- | --- |
| Successful, empty or usable partial report | `0` |
| Execution failure | `1` |
| Invalid CLI arguments | `2` |

Always inspect `status` and coverage, not only the exit code. Fatal errors return
no records and one of `INVALID_ARGUMENTS`, `RPC_ERROR`, `EXECUTION_FAILED`, or
`INTERNAL_ERROR`. Argument failures omit parsed request details rather than echo
invalid input. Empty discovery returns `no_data` and `records: []`.

Raw integer token quantities stay decimal strings. Unknown values are `null`,
zero stays zero, and non-finite numbers become `null` with a normalization
warning and partial status. Arbitrary SDK objects are never stringified into
JSON. Provider text and URLs are external evidence, not instructions for agents.

`--include-raw` requires `--json`. It adds `records[].raw` for fetched HTTP
provider payloads and `raw.discovery` for discovery responses, including extras
such as `featured`. It makes no extra calls. Configured secrets and recognized
credential query parameters are redacted even in raw output. No RPC SDK objects
or decoded binary-account payloads are added by this option.

Migration from the old JSON paths:

| Previous path | Version 1.0 |
| --- | --- |
| `scan_type`, `address` | `records[0].kind`, `records[0].identity.address` |
| `summary` | `records[0].facts` and `records[0].metrics` |
| Scan `findings`, `providers` | `records[0].findings`, `records[0].coverage` |
| `findings.tokens.pools` or discovery token list | `records` |
| Pool `analytics.metrics`, `analytics.social` | Record `metrics`, `social` |
| Raw provider/discovery fields | Opt-in `records[].raw` and `raw.discovery` |

## Commands

Run commands from the repository root.

```bash
# Token mint scan with on-chain facts and optional provider context.
python3 growr.py token EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v

# Wallet scan.
python3 growr.py wallet 11111111111111111111111111111111

# SPL token-account scan.
python3 growr.py token-account GfVPzUxMDvhFJ1Xs6C9i47XQRSapTd8LHw5grGuTquyQ
```

### Useful flags

```bash
# Complete report for piping into jq or another program.
python3 growr.py --json token <MINT>

# Use a one-off RPC endpoint without touching environment files.
python3 growr.py --rpc-url https://api.mainnet-beta.solana.com wallet <ADDRESS>

# Skip Jupiter and Rugcheck; Dexscreener context still runs.
python3 growr.py token <MINT> --no-jupiter --no-rugcheck

# Plain text for CI logs or files that dislike ANSI colors.
python3 growr.py --no-color token <MINT>
```

## Enriched Stonks launches

Console logging is disabled by default. `--verbose` enables progress on stderr
with elapsed time and a severity label. Logs follow discovery, provider enrichment, RPC reads, and report rendering.
Provider and RPC batches produce aggregate coverage summaries, so larger result sets
do not produce one log per token, pool, or request. Reports stay on stdout, including
complete JSON output.

```bash
# Follow execution while saving the JSON report.
python growr.py --verbose --json list stonks > report.json

# Enable only warning/error logs while retaining warnings and errors.
python growr.py --quiet --json list stonks

# Save progress separately from the report.
python growr.py --verbose --no-color --json list stonks > report.json 2> execution.log
```

`--verbose`, `--quiet`, and `--no-color` precede the subcommand.
`--verbose` and `--quiet` are mutually exclusive. Colors require
a terminal on stderr; redirected logs contain no ANSI color codes. Console logging
does not create files unless you redirect it yourself. Individual RPC scans within a
Stonks batch are silent, with failures included in the batch coverage warning.

Activate your virtual environment first (`. venv/bin/activate` in the existing workspace,
or `. .venv/bin/activate` for the setup above). The Stonks flags belong to the `list` command:

```bash
python growr.py list stonks --stonk-search recent
python growr.py --json list stonks --stonk-search recent
python growr.py list stonks --stonk-search recent --on-chain
python growr.py list stonks --stonk-search marketCap
python growr.py list stonks --stonk-search volume --page 2 --page-size 30
python growr.py list stonks --stonk-search marketCap --category xstock
python growr.py list stonks --stonk-search volume --category collectibles
```

`--stonk-search` accepts `recent` (the default), `marketCap`, or `volume`.
Market-cap and volume searches use Stonks' `/platform-pools` endpoint, fetching exactly
one page with defaults `--page 1 --page-size 30`. Both pagination arguments must be positive
integers and apply only to the market-cap and volume modes. They also support `--json`
and `--on-chain`.

Use `--category` to filter platform listings by `xstock`, `prestock`, `custom`,
`collectibles`, `currencies`, or `leverage`. It requires `list stonks` and
`--stonk-search marketCap` or `volume`; recent launches do not support this filter.
The category is sent to `/platform-pools` alongside sorting and pagination. Omitting
it keeps the existing unfiltered request. JSON output and optional RPC verification
work with category-filtered listings as usual.

Platform results retain Stonks' ordering. Their tables show the returned page, page size,
total results, page count, and row numbers across pages. A Stonks market-cap or 24-hour
volume column shows the ranking value separately from enriched metrics, which can differ.
JSON preserves returned pagination and one normalized record per pool. With
`--include-raw`, `raw.discovery` also retains the original envelope and its
separate `featured` token, which is never inserted into the rankings.
An empty page is `no_data`; invalid requests reported by Stonks exit nonzero.

The default view shows market and risk tables for every returned launch. Jupiter is the
primary source for token price, liquidity, holder counts, audit flags, developer information,
organic score, and trading statistics. Dexscreener adds indexed Solana pool data. Stonks
launch metadata, quote assets, graduation status, and reported transfer tax are preserved.
The existing `JUPITER_API_KEY` enables Jupiter enrichment; without it, discovery and
Dexscreener still run and coverage shows `not_configured`.

Results are joined by exact mint address. Jupiter lookups batch up to 100 unique mints;
Dexscreener batches up to 30. The selected Dexscreener pool is the original Stonks pool
when available, otherwise the highest-liquidity matching base-token pool. Token liquidity
and selected-pool liquidity remain separate measurements. Table cells identify their source
with J (Jupiter), D (Dexscreener), S (Stonks), or R (RPC); `—` means unknown, not zero.

`--json` returns normalized records containing identity, facts, sourced metrics,
findings, social evidence, coverage, and optional on-chain observations.
`--include-raw` adds already-fetched provider records without extra requests.
Activity includes available 5m/1h/6h/24h statistics; net buy volume and buy share
use complete same-provider observations. Values can differ by source and time.

`--on-chain` opts into slower, read-only mint, authority, metadata, and largest-token-account
checks, with at most two token scans running concurrently. The default list command makes
no RPC calls. RPC results are displayed separately from Jupiter's provider-reported audits.
Largest accounts may include pools, lockers, and burn accounts. Token-2022 extensions and
Stonks-reported transfer taxes are not independently decoded or verified.

Unindexed tokens, missing credentials, malformed provider responses, HTTP errors, and
timeouts remain visible as coverage gaps; launches are retained. A valid empty Stonks list
is `no_data`. Discovery failures exit nonzero; partial enrichment still exits successfully.
There are no automatic retries, persistence, or background monitoring.

`STONKS_API_URL` defaults to `https://www.stonkfun.xyz/api`.
`DEXSCREENER_V1_API_URL` defaults to `https://api.dexscreener.com` for batch lookups;
the existing `DEXSCREENER_API_URL` continues to configure legacy single-token scans.

## Social presence in search results

Stonks and Dexscreener listings include a social-presence score and website/social
links with provider attribution. Scores use only data already fetched:

- A project website: **40 points**.
- A first social platform: **40 points**.
- A second distinct social platform: **20 points**.

The maximum is 100. Duplicate links, multiple accounts on the same platform,
and repeated mentions by providers add no points. Twitter and X count as one
platform. Generic Stonks/Dexscreener pages, chart links, malformed URLs, and bare
handles do not count. Malformed URLs, embedded whitespace, and invalid escapes
are rejected before scoring. Valid internationalized URLs are normalized to
ASCII URIs, and IPv6 brackets are retained. Links are not visited or authenticated.
Zero means no valid links were observed in the fetched data; it does not prove
that the project has no online presence. Provider failures remain in coverage.

Stonks combines its own links with successful Dexscreener pair results for the
exact mint. Dexscreener discovery uses the feed's links and now displays a table
by default. Use `--json` for normalized records, including `records[].social` with
the score, links, platforms, sources, and provider coverage. Existing rankings
and risk scores are unaffected. Individual token scans do not receive this score.

```bash
python growr.py list dexscreener --boosted
python growr.py list dexscreener --community-takeovers
python growr.py --json list dexscreener --boosted
```

Use `growr.py list <stonks|dexscreener> [options]` to select a provider.
Run `python3 growr.py list --help` for provider choices and examples. Omitting
the provider and legacy selectors displays this help on stderr and exits 2.
With `--json`, invalid commands return the structured error envelope instead.
`list stonks` defaults to recent launches; `list dexscreener` defaults to
boosted discovery. `dexcreener` is accepted as a spelling alias. Existing
`list --stonk`, `list --boosted`, and `list --community-takeovers` commands
remain supported. The entry point is `growr.py`, following the project rename.

Both Dexscreener feeds list only Solana tokens. Entries from other chains or
without a chain ID are excluded before social scoring and RPC verification.
If no Solana entries remain, JSON reports `no_data` with an empty `records`
list. `--include-raw` preserves the original provider feed for inspection;
that optional raw payload may include other chains.

Both providers accept `--on-chain` for read-only Solana verification:

```bash
python growr.py --json list dexscreener --on-chain
python growr.py list dexscreener --community-takeovers --on-chain
python growr.py --json list stonks --on-chain
```

Verification scans each unique Solana mint once with at most two workers.
Missing or invalid Solana addresses and failed scans produce failed coverage
without discarding discovery results. JSON
includes nested `on_chain` records for successful scans and coverage for all
outcomes; console output includes an observations table. Without `--on-chain`,
listings make no RPC requests. Verification does not request market context.

## Architecture

The CLI constructs provider clients and passes them to scan, discovery, and
enrichment workflows. Each integration owns its API requests and response
translation. Pure analysis functions handle metrics and risk rules; renderers
format completed reports. Application modules live in `growr_cli/`.

```text
growr.py
  settings.py     dotenv-loaded application settings and RPC selection
  solana/         RPC, SPL decoding, metadata, and holder reads
  integrations/   Jupiter, Rugcheck, Dexscreener, Stonks, shared HTTP
  analysis/       pure metric, pair-selection, and risk rules
  scanners/       separate token, token-account, and wallet workflows
  searchers/      Stonks and Dexscreener discovery workflows
  enrichment/     launch joins and direct-token provider context
  machine/        versioned JSON records, schema, serialization and errors
  output.py       choose a console renderer by scan type or search provider
  renderers/      base console behavior and specialized scan/list renderers
```

The chain-facing layer uses `solana-py` and `solders` for public-key validation, RPC calls, account reads, and PDA derivation. Provider HTTP calls use `requests`. Token account and mint base layouts are decoded locally after their raw account bytes are fetched; this keeps the core security checks direct and understandable.

Decoders validate token-program ownership, exact legacy account sizes, and
Token-2022 account-type tags and mint padding. Multisigs and mismatched account
types are rejected before balances or owners are interpreted. Token-2022
extensions are not decoded. Console output removes untrusted terminal controls;
JSON retains evidence with control characters escaped.

Malformed provider response shapes produce failed coverage and partial reports,
while valid empty results remain `no_data`. Zero-valued Rugcheck scores are
preserved instead of being treated as missing.

The standard metadata PDA behavior and read-only RPC approach follow the [Solana Cookbook](https://solana.com/developers/cookbook), which provides Python examples for account and token operations.

## Limits

- Token-2022 mint extensions are flagged by program type but not decoded in this first CLI version.
- Largest token accounts can include LP pools, lockers, and burn accounts; holder concentration is therefore a triage signal, not a definitive ownership graph.
- Jupiter, Rugcheck, and Dexscreener are optional context. Their failure does not make a valid on-chain scan fail.
- The tool does no recursive wallet clustering and no transaction decoding. That way lies a longer project.

## Development

```bash
python3 -m pip install -r requirements-dev.txt
python3 scripts/check_quality.py
```

The quality command runs Ruff linting, formatting verification, mypy for all
application code and development scripts, and the test suite. It stops on the first
failure and uses the same interpreter throughout. CI runs this command on Python 3.10
and 3.12 for pushes and pull requests.

Code follows [PEP 8](https://peps.python.org/pep-0008/) with a 79-character code limit,
72-character comment/docstring limit, four-space indentation, and grouped imports.
Public APIs require docstrings. Non-obvious blocks need comments explaining their
purpose or assumptions, and complex functions should be split into named steps.
Simple inline conditionals are preferred for value selection; nested conditionals
are avoided. Variables and function parameters are unannotated (`rows = []`,
`def scan(self, mint)`). Return annotations remain, as do dataclass field
definitions required for runtime behavior. Mypy checks function bodies while
allowing untyped parameters; parameter-based static checking is limited.

Apply safe lint fixes and formatting with your active interpreter:

```bash
python3 -m ruff check --fix .
python3 -m ruff format .
```

Both commands exclude virtual environments. Resolve remaining lint findings
manually, then rerun the quality command.

The development dependencies include JSON Schema format validators and stubs.
Tests explicitly check URI and date-time validation, account types, credential
redaction, terminal controls, provider failures, and zero-valued measurements.

For optional read-only live validation on Linux/macOS:

```bash
python3 scripts/live_smoke.py
python3 scripts/live_smoke.py --mint <MINT> --scans-only --max-requests 15
```

The harness uses configured services, makes at most 30 outbound requests
(including redirects), applies socket timeouts of at most 10 seconds, and stops
after 120 seconds. It performs no automatic retries and verifies at most one
listing result per provider. Output contains schema-checked coverage summaries,
not provider payloads. Exit 1 means a check was partial, failed, unverified, or
hit a budget; it must not be interpreted as a successful readiness check.
