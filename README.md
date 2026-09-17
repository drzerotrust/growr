# growr

Read-only Solana research data for agents and automated reporting pipelines.
Use `--json` for a versioned evidence contract, or run without it for console
tables. growr retrieves observations and reports coverage; the consuming agent
handles scheduling, comparisons, selection, and narrative report generation.

It scans:

- token mints: authorities, standard Metaplex metadata, largest token accounts, Jupiter market/activity enrichment and social evidence, plus optional Rugcheck
- SPL Token / Token-2022 token accounts: mint, owner, balance, state, delegate, close authority, and basic owner-wallet context
- wallets: SOL balance and exact lamports, recent signature records, and SPL Token / Token-2022 account addresses, mints, raw balances, states and counts

Use `list` to browse feeds, `search <jupiter|stonks> <QUERY>` to find candidates,
and `token <MINT>` to analyze a selected mint. Search returns the selected
provider's available market/social data without RPC calls or automatic selection.

The scanner does not sign, send, or simulate transactions, or persist analysis results.
It asks public/provider APIs and prints the answers. Install the `growr`
executable, or run `python3 growr.py` from a source checkout.

## Search examples

After installing the requirements below, use
`python3 growr.py search <provider> <query>`. The provider is `stonks` or
`jupiter`; quote queries that contain spaces.

```bash
# Search Stonkfun by name, symbol or mint; no API key required.
python3 growr.py search stonks te

# Return JSON for an agent or reporting pipeline.
python3 growr.py --json search stonks te

# Sort matching tokens by volume and request the second page.
python3 growr.py search stonks te --sort volume --page 2 --page-size 10

# Find the newest matching tokens, including the original API response.
python3 growr.py --json --include-raw search stonks te --sort newest

# Search Jupiter after setting JUPITER_API_KEY in .env.
python3 growr.py search jupiter JUP
python3 growr.py --json search jupiter "Wrapped SOL"

# Show every search option and more examples.
python3 growr.py search --help
```

Search returns candidate mint addresses and available market/social data.
Choose a returned mint for a separate `token` command to run on-chain analysis.
Put global flags such as `--json` before `search`. See
[Token search](#token-search) for provider options and output details.

## Requirements

- Python 3.10+
- A Solana mainnet RPC endpoint, optional but recommended for reliable results

Install Growr from the repository root:

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install .
growr --version
growr doctor --json
```

The package includes all five playbooks and installs the `growr` executable.
Use `growr` wherever the examples below show `python3 growr.py`.
`python3 -m growr_cli` is also supported. For source development, use
`python3 -m pip install -e '.[dev]'`; the original script commands still work.

After the v0.3.0 Git release is published, an isolated tool install can use:

```bash
uv tool install "git+https://github.com/drzerotrust/growr.git@v0.3.0"
```

The tag must exist before that command can work. A local development install
can use `uv tool install /absolute/path/to/growr`. The wheel and source archive
contain application code and licensing; credentials, local docs, skills,
the interactive client and the web application are excluded.

## Environment

Configure `.env` in the repository root (next to `growr.py`) before running,
or deliberately use the built-in defaults shown in `.env.example`. Process
environment variables override `.env` values. Copy the included example and
add credentials for the services you want to enable. Never commit real keys.

```bash
cp .env.example .env
```

For installed use outside a checkout, set `GROWR_ENV_FILE` to a private dotenv
file, or configure provider variables directly in the execution environment:

```bash
export GROWR_ENV_FILE="/absolute/path/to/private/growr.env"
growr doctor --json
```

File precedence is explicit `GROWR_ENV_FILE`, a source checkout's `.env`, then
`$XDG_CONFIG_HOME/growr/.env` (or `~/.config/growr/.env`). Existing process
variables always win. Growr does not load `.env` from an arbitrary working
directory or an installed site-packages directory. An explicitly selected
missing, unreadable or malformed file fails configuration checks without
printing its path or contents. Help/version/schema and offline playbooks can
still run. Child processes inherit the selected environment.

The example works unchanged: blank keys select public Solana RPC and leave
Jupiter enrichment unconfigured. No API key is required for basic RPC scans
or Stonks discovery. Jupiter discovery requires a Jupiter API key. Set `HELIUS_API_KEY` to select Helius and
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

`RUGCHECK_API_URL`, `JUPITER_API_URL`, and `STONKS_API_URL` configure
provider API bases. `STONKS_HOLDERS_API_URL` configures the full legacy
holder endpoint used only by `token --stonk`. Defaults are in `.env.example`.
Jupiter uses `https://api.jup.ag/tokens/v2` for both discovery and enrichment.

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

Version **2.2** adds Stonkfun reward totals and optional snapshot comparisons
to the JSON contract. Search remains available for Jupiter and Stonks.
Console tables remain the default; `--json` selects the agent-facing format
for every scan, listing and search.
Global flags precede the subcommand. There is no legacy JSON mode.

```bash
python growr.py --json token <MINT>
python growr.py --json search jupiter JUP
python growr.py --json search stonks te
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

| Previous path | Current envelope |
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

# Single Stonkfun token with RPC checks and Stonkfun context.
python3 growr.py token <MINT> --stonk

# Wallet scan.
python3 growr.py wallet 11111111111111111111111111111111

# SPL Token or Token-2022 token-account scan.
python3 growr.py token-account GfVPzUxMDvhFJ1Xs6C9i47XQRSapTd8LHw5grGuTquyQ
```

`token-account` accepts the holding account for a specific mint and owner.
For a holder's wallet address, use `wallet <ADDRESS>`; for the coin itself,
use `token <MINT>`. Both SPL Token and Token-2022 base account fields are
supported, but Token-2022 extension bodies are not decoded. A wallet can
have zero data bytes, so a wallet address cannot be decoded as a token account.

### Wallet token-account inventory

Wallet scans include each validated token account in both the console table
and `records[0].facts.token_accounts.entries` in JSON. No extra flag or
per-account RPC lookup is needed; Growr decodes the account data returned by
the existing SPL Token and Token-2022 inventory requests.

```bash
python3 growr.py wallet Beqv6dzTcjV2eodo8RRXCiCcnSYrS1vkQKhfqwHXqeit

# Save a machine-readable inventory, then extract its token-account addresses.
python3 growr.py --json wallet <WALLET> > wallet.json
jq -r '.records[0].facts.token_accounts.entries[].address' wallet.json

# Copy a returned address into a focused account scan.
python3 growr.py token-account <TOKEN_ACCOUNT>
```

Each entry contains:

| Field | Meaning |
| --- | --- |
| `address` | Token-account address for a subsequent `token-account` scan |
| `mint` | Mint held by this account |
| `token_program` | `spl_token` or `token_2022` |
| `raw_amount` | Exact integer balance as a decimal string, before mint-decimal conversion |
| `state` | `uninitialized`, `initialized`, or `frozen` |

Zero-balance accounts remain in the inventory. Entries preserve RPC order
within each program, with SPL Token first and Token-2022 second. Accounts for
the same mint remain separate; Growr does not sum balances or value holdings.

Existing account counts describe returned RPC entries. Unusable or duplicate
entries are omitted from `entries` and counted in `unparsed_account_count`,
with partial coverage and a console finding. A failed program lookup has a
null count and failed coverage; the other program's entries remain available.
Two successful empty lookups produce an empty array and zero counts. Usable
partial reports still exit 0, so pipelines should inspect `status` and
`coverage` before treating an empty array as a complete inventory.

### Useful flags

```bash
# Complete report for piping into jq or another program.
python3 growr.py --json token <MINT>

# Use a one-off RPC endpoint without touching environment files.
python3 growr.py --rpc-url https://api.mainnet-beta.solana.com wallet <ADDRESS>

# Read only the chain by skipping both context providers.
python3 growr.py token <MINT> --no-jupiter --no-rugcheck

# Plain text for CI logs or files that dislike ANSI colors.
python3 growr.py --no-color token <MINT>
```

## RPC request budgets

Updated on 2026-09-16 for one successful invocation. RPC calls and market
provider HTTP requests are counted separately:

| Command | Solana RPC calls | Other HTTP requests |
| --- | --- | --- |
| `wallet <WALLET>` | 4 | 0 |
| `transaction <SIGNATURE>` | 1 | 0 |
| `history <ADDRESS>` | 1 | 0 |
| `history <ADDRESS> --details --limit N` | Up to 1 + N | 0 |
| `token-account <ACCOUNT>` | 3 | 0 |
| `token <MINT>` | 3–4 | Up to 1 Jupiter + 1 Rugcheck |
| `token <MINT> --no-jupiter --no-rugcheck` | 3–4 | 0 |
| `token <MINT> --stonk` | 3–4 | 4 Stonkfun |
| `list jupiter` | 0 | 1 Jupiter |
| `list stonks` | 0 | 1 Stonkfun + optional Jupiter enrichment batches |
| `list <provider> --on-chain` | 3–4 per unique valid mint | Same as the corresponding list |
| `search jupiter <QUERY>` | 0 | 1 Jupiter |
| `search stonks <QUERY>` | 0 | 1 Stonkfun |
| `schema`, any `--help` | 0 | 0 |

A wallet uses `getBalance`, `getSignaturesForAddress(limit=10)` and two
`getTokenAccountsByOwner` calls, one for each token program. Hundreds of
returned token accounts still cost four calls. A token-account scan reads
that account, then the owner's balance and signatures: three calls.

A token scan reads the mint, derived Metaplex metadata, largest accounts,
and a single batch of those accounts to resolve owners. Empty largest-account
results skip the batch, giving three calls. Metadata address derivation and
inventory decoding are local. Listing verification deduplicates mints and
uses at most two concurrent mint scans; 30 distinct mints normally mean 120
RPC calls. Concurrency reduces elapsed time, not the number of calls.

Stonks list enrichment batches up to 100 distinct mints per Jupiter request
when its key is configured. A conforming nonempty CLI page normally adds one
Jupiter request; empty lists or missing keys add none. Search does not enrich.
`--stonk` token context requests market, holders, burns and rewards once each.

`--json`, `--include-raw`, logging and valid `--compare-to` add no
requests. There is no automatic retry. Provider HTTP redirects are rejected
so they cannot silently exceed the cap. Request counts are not provider
billing credits; no credit cost is inferred.

Each run shares a thread-safe budget, including listing verification workers.
Global `--max-rpc-calls` defaults to 500 and `--max-http-calls` to 100.
Exhaustion stops new requests and appears as failed/partial coverage;
existing usable observations remain available. Global `--commitment` accepts
`finalized` (default) or `confirmed`. Put these flags before the command:

```bash
python3 growr.py --json --max-rpc-calls 11 history <ADDRESS> --details --limit 10
python3 growr.py --json --commitment confirmed wallet <WALLET>
```

`run.requests.rpc` and `run.requests.http` contain `attempted`, `failed`,
`blocked`, and `limit`. A failed attempt consumes budget; a blocked reservation
never reaches transport. `run.requests.observations` retains method, subject
where applicable, commitment, retrieval time and response context slot.
Signatures carry transaction slots; methods without a response context have
a null receipt slot. `getMultipleAccounts` is one RPC method request.
Provider payload parsing failures can still appear in coverage after a
successful transport attempt. `coverage.counts` remains an outcome count.

The selected endpoint has a safe label in `request.rpc`; Growr does not
independently verify its cluster with an extra genesis-hash request.
Observations from different calls are not one atomic snapshot. Wallet
`facts.sol_lamports` preserves the exact integer string alongside the
existing approximate `sol_balance` display number.

## Investigation playbooks

Installed commands work from any directory:

```bash
growr playbook token-holders <MINT> --json
growr playbook wallet-holdings <WALLET> --json
growr playbook activity <WALLET> --json
growr playbook shared-holdings holders.json --json
growr playbook token-screen --criteria criteria.json --provider jupiter --json
growr playbook --help
```

Each recipe supports `--help`; put its limits after its name. Only `--json`
may precede `playbook`; other global controls are rejected rather than
silently ignored. Playbook JSON remains contract 1.1. The source scripts below
are compatibility entry points into the same packaged implementations.

Choose the workflow by the question you want to answer:

| Script | Purpose |
| --- | --- |
| `token_screen.py` | Evaluate discovery candidates or explicit mints against measurable criteria. |
| `token_holders.py` | Inspect sampled owners and their other holdings. |
| `wallet_holdings.py` | Inspect one wallet's current balances and metadata. |
| `shared_holdings.py` | Compare holdings within a saved owner cohort, offline. |
| `activity.py` | Inspect bounded address references and transaction bodies. |

The executable playbooks call `python -m growr --json` through `subprocess`
using the same interpreter and combine its public reports. Child commands
inherit the selected environment configuration. Configure `JUPITER_API_KEY` for
the default metadata lookup, or use `--no-jupiter` to skip it.

```bash
# Find sampled owners and their balances, with Jupiter metadata.
python3 scripts/playbooks/token_holders.py <MINT>

# Inspect one wallet directly, with machine-readable output.
python3 scripts/playbooks/wallet_holdings.py <WALLET> --json

# Permit up to ten additional RPC scans if Jupiter cannot supply units.
python3 scripts/playbooks/token_holders.py <MINT> \
  --wallet-limit 5 --mint-limit 10 --json

# Limit metadata enrichment to the first 100 distinct holding mints.
python3 scripts/playbooks/wallet_holdings.py <WALLET> \
  --jupiter-batch-limit 1 --json

# Skip Jupiter and additional mint scans; keep unknown quantities raw.
python3 scripts/playbooks/token_holders.py <MINT> --no-jupiter --json

# Resolve units through RPC instead of Jupiter.
python3 scripts/playbooks/wallet_holdings.py <WALLET> \
  --no-jupiter --mint-limit 10

# Save a report under the ignored data directory.
mkdir -p data
python3 scripts/playbooks/token_holders.py <MINT> \
  --json > data/token-investigation.json

python3 scripts/playbooks/token_holders.py --help
python3 scripts/playbooks/wallet_holdings.py --help
```

`token_holders.py` groups the largest token accounts by their reported
owner, ranks those owners by the summed balance **within that sample**,
and scans up to five distinct owners by default. It preserves each sampled
account and its rank. These are address observations, not a complete holder
census or verified people; pools and program authorities can appear.

Both scripts combine each wallet's nonzero accounts by mint and token
program, retaining individual addresses, raw balances and frozen states.
`raw_amount` is an exact integer string from RPC. Zero accounts are omitted
and counted. `is_target` distinguishes the original token from other
holdings; it is false for all standalone wallet results.

After reading the wallets, the playbook deduplicates holding mints across
all inventories and calls `growr.py --json search jupiter <MINTS>` in batches
of up to 100 exact addresses. Metadata includes available names, symbols,
icons, social links, verification status, token price and update time.
A token held by several wallets is looked up once. Prices remain Jupiter
observations; no USD portfolio value is calculated.

Console token quantities use thousands separators and retain every decimal
place. Individual account rows also show token quantities when decimals are
known: `1200000000` raw units with six decimals becomes `1,200 tokens`.
Unknown decimals leave a grouped raw balance, such as `1,234 raw units`.
JSON keeps exact, ungrouped strings, including every account's raw balance.

Known RPC decimals take precedence. Otherwise, valid Jupiter decimals and
a matching token program convert raw balances into exact decimal strings.
`amount_source` identifies `rpc` or `jupiter`; `metadata_conflicts` records
conflicting Jupiter units without replacing known RPC units. Names remain
available even if decimals are missing. Optional RPC fallback scans only
mints whose units remain unresolved, caching success and failure.

| Option | Default | Scope |
| --- | --- | --- |
| `--wallet-limit` | 5 | Token playbook only; 1–20 distinct sampled owners |
| `--jupiter-batch-limit` | 10 | 1–10 batches, each with at most 100 distinct mints |
| `--no-jupiter` | Off | Skip Jupiter metadata; no Jupiter key needed |
| `--mint-limit` | 0 | 0–50 additional RPC mint scans for unresolved units |
| `--timeout` | 30 | 1–120 seconds for each child process |
| `--json` | Off | Emit one playbook document instead of console output |

Limits apply across the entire run. Lookups follow wallet inventory order;
raw balances of different tokens do not rank portfolio value. Holdings stay
in the report when metadata is unavailable or a budget is exhausted.
`amount_tokens` stays null with an explanatory `amount_status` when units
cannot be resolved. `--mint-limit 0` disables RPC fallback; combine it with
`--no-jupiter` for raw quantities except where the initial target scan
already supplied units.

Each wallet uses four RPC calls; each token scan uses three or four and
disables its individual Jupiter/Rugcheck context. Each Jupiter batch uses
one HTTP request and zero RPC calls. Default token investigation is capped
at **24 RPC calls plus 10 Jupiter HTTP requests**, across at most 16 child
commands. A standalone wallet is capped at **4 RPC calls plus 10 Jupiter
HTTP requests**, across at most 11 children. Five distinct mints across five
selected wallets normally need just one Jupiter batch: at most 24 RPC
calls plus one HTTP request. Every permitted fallback token scan adds up
to four RPC calls. Subprocess counts are measured; the caps above are
upper estimates. `budget.measured` also sums validated child request counts
and reports children with unknown measurements. Calls are sequential, with no retries or recursive
expansion into other holders.

Playbook JSON uses `playbook_version: "1.1"`, separate from Growr schema 2.2.
`sample` describes selected owners; `wallets[].holdings` contains balances,
amount provenance and per-holding `metadata`. `metadata_lookups` contains
one Jupiter outcome per mint; `mint_lookups` contains cached RPC unit
outcomes. Metadata `scan_index` is a zero-based reference into `scans`,
which retains child commands, run timestamps, coverage, exit codes and safe
error codes. Skipped or over-budget lookups have no scan index. Reports
exclude child stderr, raw payloads and RPC endpoints.

Failed wallet inventories have `holdings: null`; successful empty ones
have `holdings: []`. Missing Jupiter IDs are `no_data`, failed batches are
`failed`, and lookups beyond the cap are `budget_exhausted`. These gaps,
conflicting units and incomplete inventories mark investigations partial;
explicitly skipped lookups do not. An absent Jupiter key leaves usable RPC
balances in a partial report. Usable partial reports exit 0; initial scan
failure exits 1 with an error report; invalid arguments exit 2 with usage
on stderr. Scans happen at separate times, so sampled balances and later
wallet balances can differ. Holdings do not establish purchases,
transferability, shared control or bundle membership.

### Reading playbook output

For `python3 scripts/playbooks/token_holders.py <MINT> --wallet-limit 2`,
the following illustrative excerpt uses fictional balances and replaces
addresses with descriptive placeholders. The closing notes are omitted.

```text
growr playbook | token_holders | partial
Target: <TARGET_MINT>
Sample: 3 token accounts; 2 owners selected; 0 unresolved

Wallet: <WALLET_A> [success]
  Target tokens in sample: 1,000
  Inventory complete: True
  SOL balance: 1.5
  target <TARGET_MINT>: 1,200 tokens
    TGT Target Token
    Jupiter metadata: success; amount source: rpc
    <TARGET_ACCOUNT>: 1,200 tokens [initialized]
  holding <OTHER_MINT>: 2.5 tokens
    EX Example Token
    Jupiter metadata: success; amount source: jupiter
    Jupiter price USD: 1.25
    <OTHER_ACCOUNT_1>: 1.5 tokens [initialized]
    <OTHER_ACCOUNT_2>: 1 tokens [initialized]
  holding <UNINDEXED_MINT>: 1,234 raw units (no_data)
    Jupiter metadata: no_data; amount source: unknown
    <UNINDEXED_ACCOUNT>: 1,234 raw units [initialized]

Wallet: <WALLET_B> [failed]
  Target tokens in sample: 500
  Inventory complete: False
  SOL balance: None
  Holdings unavailable; inspect scans in the JSON report.

Child commands: 4; estimated RPC calls: at most 12; Jupiter HTTP requests: at most 1
```

| Output | How to read it |
| --- | --- |
| `Target: <TARGET_MINT>` | The mint supplied to the token-holder script. It is the token being investigated. |
| `3 token accounts; 2 owners selected; 0 unresolved` | The initial sample returned three accounts. Their owners were resolved, and two distinct owners were selected for wallet scans. This does not establish a complete holder census or guarantee that those later scans succeed. |
| `Target tokens in sample: 1,000` | Wallet A's summed target-token balance in the initial largest-account sample. Only sampled accounts contribute to this number. |
| `target <TARGET_MINT>: 1,200 tokens` | Wallet A's target-token balance across its returned accounts in the later wallet scan. This includes accounts outside the initial sample. Different coverage and scan times can explain a difference; it does not prove a purchase. |
| `holding <OTHER_MINT>: 2.5 tokens` | A different token held by wallet A. Each `holding` line identifies that token by its mint; the symbol and name appear underneath when available. |
| Indented account addresses and quantities | The individual token accounts contributing to the holding. Here, `1.5 + 1` tokens equals the `2.5` token total. Each account uses the holding's known decimals; amounts stay labeled `raw units` when those decimals are unavailable. `[initialized]` is the account state, not a safety rating. |
| `amount source: rpc` / `jupiter` | Where the decimals used to convert the raw balance came from. Raw balances come from RPC in both cases. Jupiter can supply a name even when RPC supplies the decimals. |
| `Jupiter price USD: 1.25` | Jupiter's reported price per token. The playbook does not calculate this wallet's USD holding value. |
| `Inventory complete: True` with wallet `[success]` | Both token-program inventories were read without omitted malformed entries. Metadata availability is separate, so an unindexed holding can still appear beneath a successful wallet. |
| Wallet B `[failed]`, `None`, and unavailable holdings | Its wallet scan failed. The earlier sampled balance of `500` remains usable, but its current SOL balance and inventory are unknown. Neither should be treated as zero. |
| Header `partial` | Some requested observations are missing. Here, wallet B failed and one holding lacks metadata; wallet A's known balances remain usable. |

For `<UNINDEXED_MINT>`, Jupiter returned no matching record (`no_data`).
The script still found `1,234` raw units through RPC, but cannot convert
them without decimals. This does **not** mean 1,234 tokens, an empty
balance, or a failed transaction. A metadata status of `failed` instead
means the lookup did not complete successfully; `budget_exhausted` means
the configured lookup allowance was used up. Inspect `metadata_lookups`
and the corresponding `scans` receipts in `--json` output for details.

The four child commands are one token scan, two attempted wallet scans
and one Jupiter search. The reported network counts are upper estimates;
the failed wallet command may have stopped before making all its calls.

For `wallet_holdings.py`, the top-level `Target` is the supplied **wallet
address**. There is no target token or largest-account sample: every token
line is labeled `holding`. The amount, metadata and failure explanations
above apply to both scripts. `SOL balance` is the wallet's native SOL
balance, reported separately from its token-account holdings.

The manual recipes below expose the same individual commands. Their JSON
extraction examples require `jq`; the Python playbooks do not. Use `history`
and `transaction` for RPC evidence, or the bounded `activity.py` playbook
to combine explicit address histories with deduplicated transaction reads.

### 1. Find the largest accounts and their owners

```bash
python3 growr.py --json token <MINT> \
  --no-jupiter --no-rugcheck > token.json
jq '{status, coverage}' token.json
jq '.records[0].facts.holders.top_accounts' token.json
jq -r '[.records[0].facts.holders.top_accounts[]
  | .owner | select(. != null)] | unique[]' token.json > owners.txt
```

Rows contain token-account address, resolved owner, balance and supply share.
This is the largest-account sample, not every holder or a list of verified
people. Pools and lockers can appear, and one owner may control several
accounts. Use `token <MINT> --stonk` for additional platform-reported holders.
A complete holder census needs a separate paginated workflow, such as mint
queries through [Helius getTokenAccounts](https://www.helius.dev/docs/api-reference/das/gettokenaccounts),
followed by owner aggregation; Growr does not implement that workflow yet.

### 2. Inspect what else a selected wallet holds

```bash
python3 growr.py --json wallet <WALLET> > wallet.json
jq '{status, coverage}' wallet.json
jq -r '[.records[0].facts.token_accounts.entries[]
  | select(.raw_amount != "0") | .mint] | unique[]' wallet.json
```

Select a few distinct owners from the token scan instead of automatically
scanning every account. A token scan plus five owner-wallet scans normally
costs 24 RPC calls. Inventory includes zero balances; the query above selects
nonzero holdings without converting large integers to floating point.
Possession does not establish a purchase: unsolicited tokens may appear.

### 3. Select a token account for closer inspection

```bash
jq -r '.records[0].facts.token_accounts.entries[].address' wallet.json
python3 growr.py --json token-account <TOKEN_ACCOUNT> > account.json
```

Use a returned account address, not the wallet or mint. The scan exposes
state, delegate, close authority and basic owner context. Its recent-signature
count belongs to the owner wallet, not to the token-account address.

### 4. Read recent activity and individual transactions

```bash
# One page of signatures, with execution status and slot; one RPC call.
python3 growr.py --json history <WALLET> --limit 10 > history.json

# Query the token account itself for its address references.
python3 growr.py --json history <TOKEN_ACCOUNT> --limit 10 --details

# Continue with pagination.next_before from a full page.
python3 growr.py --json history <ADDRESS> --before <SIGNATURE> --limit 10

# Inspect one transaction, without a preliminary address search.
python3 growr.py --json transaction <SIGNATURE>
```

`history` accepts `--limit` from 1–100 (default 20), exclusive `--before`
and `--until` signature bounds, and `--details`. It fetches one page only.
Details add one call per distinct signature. JSON uses a `history` record
with `facts.entries`; each entry retains its signature, slot, block time,
confirmation status, execution error and `detail_status`. Top-level
`pagination` repeats the window and continuation. A short page exhausts
this provider page, not necessarily lifetime history.

A `transaction` record uses `identity.signature` and `facts.transaction`.
It contains legacy/v0 transaction evidence: fee payer, signers, fees in
lamports, exact before/after native and token balances, instructions, logs,
and recognized System/token events with signature, slot and outer/inner
instruction positions. Missing token-balance sides and owners stay null.
Amounts use integer strings. Token-account transfer endpoints are account
addresses; they are not silently labelled wallet authorities.

Failed transactions retain fees and balance observations but emit no
completed events. Inner actions with missing execution logs or a caught
program failure remain instructions rather than asserted movements.
Unknown programs are retained without guessing swaps. `recording` and
coverage expose missing metadata. Missing bodies and unsupported transaction
versions remain gaps, with usable partial reports exiting 0.

Wallet scans now retain the ten signature records they already fetched,
without extra calls. A `token-account` scan still puts the owner's activity
under `owner_wallet`; use `history <TOKEN_ACCOUNT>` for the account itself.
Address references can miss incoming transfers mentioning only another token
account, including closed accounts. Helius indexed-owner history, funding
traversal, bundle attribution and protocol-specific swap decoders remain
future work.

### 5. Run the activity playbook

```bash
python3 scripts/playbooks/activity.py <WALLET> --json > activity.json
python3 scripts/playbooks/activity.py <WALLET> \
  --token-account <TOKEN_ACCOUNT> --limit 10 --pages 2 \
  --transactions 20 --max-rpc-calls 30 --json
```

This script calls Growr through bounded subprocesses. It first reads
references for the supplied addresses, then fetches each distinct transaction
body once across the investigation. It never automatically discovers more
accounts or traverses counterparties.

Defaults: 10 signatures per page, one page per address, up to 20 unique
bodies, 50 total RPC calls, and 30 seconds per child. `--token-account` may
be repeated up to ten times. Limits are `--limit` 1–100, `--pages` 1–10,
`--transactions` 1–100, `--max-rpc-calls` 1–500, and `--timeout` 1–120.
One default address costs at most 11 RPC attempts, zero provider HTTP calls.

Playbook JSON 1.1 contains `windows` (addresses, pages, continuation and stop
reason), `transactions` (evidence plus referencing addresses/child indices),
`scans` (safe receipts), and `budget`. A stopped body budget retains the
signature with `budget_exhausted`; a failed read does not erase other
transactions. An initial total history failure exits 1, usable partial
results exit 0, and invalid arguments exit 2.

### 6. Find shared holdings in a saved cohort

```bash
python3 scripts/playbooks/token_holders.py <MINT> --json > holders.json
python3 scripts/playbooks/shared_holdings.py holders.json --json > overlap.json
```

`shared_holdings.py` reads a token-holder playbook 1.1 report of at most
10 MiB and makes **zero network calls**. It lists mint/program groups held
by at least two selected owners, with exact quantities and contributing
account addresses. `selected_owner_count` is the cohort denominator;
`known_absent` requires a complete inventory, while `unknown_presence` keeps
missing inventories explicit. Unit conflicts are flagged.

The target token and common-asset labels for wrapped SOL/USDC are identified
separately. The ordering helps inspect overlap; an unlabelled token is not
proven rare, and shared holdings do not establish common control. This
report inherits the source scan times and present-balance limitations.

Both new scripts support `--help` and `--json`, use the existing environment,
and run from any working directory when invoked by their full path.

### Application integration

An application can run these commands with an argument list, `shell=False`,
a fixed Python interpreter, and a finite subprocess timeout. Read one JSON
object from stdout and inspect `status`, `coverage` and request limits before
presenting conclusions. CLI envelopes remain schema 2.2 with additive history,
transaction and request-metering fields; playbooks use their separate 1.1
contract. `python3 growr.py schema` prints the current CLI schema.

Keep authentication and RPC logic in Growr. The UI can select a mint, run
`token_holders`, display owners and quantities, open an owner's `activity`,
and compare a saved cohort with `shared_holdings`. The CLI does not start
an HTTP server or manage application sessions.

## Screening tokens against criteria

`token_screen.py` turns a discovery page or explicit mint list into an
auditable shortlist. It separates hard requirements from ranking priorities;
it does not assign an invented investment score. Start by saving this example
as `criteria.json`, then adjust the thresholds to your research question:

```json
{
  "criteria_version": "1.0",
  "verify_on_chain": true,
  "max_age_seconds": 900,
  "requirements": [
    {"field": "liquidity_usd", "op": "gte", "value": "100000"},
    {"field": "has_website", "op": "eq", "value": true},
    {"field": "has_social", "op": "eq", "value": true},
    {"field": "freeze_authority_revoked", "op": "eq", "value": true}
  ],
  "ranking": [
    {"field": "volume_24h_usd", "direction": "desc"},
    {"field": "liquidity_usd", "direction": "desc"}
  ]
}
```

These are example thresholds, not a default strategy. All requirements must
pass. A known failure rejects a candidate; a missing required measurement
keeps it unknown. Numeric operators are `eq`, `gte`, `lte`, `gt`, `lt`;
boolean and category conditions support `eq`. Decimal strings preserve exact
thresholds. Ranking is ordered by the listed priorities (`asc` or `desc`),
with complete ranking inputs first and exact mint as the final tie-breaker.

```bash
# Discover a bounded Jupiter feed, then verify up to five candidate mints.
python3 scripts/playbooks/token_screen.py --criteria criteria.json \
  --provider jupiter --feed toptraded --interval 24h --json > screen.json

# Browse one Stonkfun category, including normal Jupiter enrichment.
python3 scripts/playbooks/token_screen.py --criteria criteria.json \
  --provider stonks --feed volume --category xstock --pages 2 --json

# Search by text, or compare explicit mint addresses.
python3 scripts/playbooks/token_screen.py --criteria criteria.json \
  --provider jupiter --query JUP --json
python3 scripts/playbooks/token_screen.py --criteria criteria.json \
  --provider stonks --query te --sort marketCap --json
python3 scripts/playbooks/token_screen.py --criteria criteria.json \
  --mints <MINT_A> <MINT_B> --json

# Recompute from a saved screen or Growr list/search report: zero requests.
python3 scripts/playbooks/token_screen.py --criteria criteria.json \
  --input screen.json --json > reranked.json

python3 scripts/playbooks/token_screen.py --help
```

Never redirect output into the criteria or input file. `--input` is always
offline, even when the saved data lacks RPC evidence. New criteria and current
freshness checks may change the outcome; old cached decisions are ignored.
Use a live input to obtain new evidence.

| Fields | Measurement and scope |
| --- | --- |
| `market_cap_usd` | Fresh Jupiter token market cap, with Stonkfun pool fallback. Conflicting pool values remain unknown. |
| `liquidity_usd` | Jupiter token liquidity, not executable depth in a particular pool. |
| `volume_24h_usd` | Jupiter buy + sell volume over 24h, or Stonkfun's reported pool volume. |
| `holder_count`, `organic_score`, `verified` | Jupiter-reported observations. |
| `has_website`, `has_social`, `social_score` | Growr's reported-link presence evidence; it does not establish authenticity. |
| `first_pool_age_hours` | Exposed Jupiter first-pool creation age, not mint creation age. |
| `top_20_accounts_pct` | RPC largest-account sample's share of supply, not distinct-owner concentration. Unknown without positive supply. |
| `initialized_mint` | RPC mint initialization status. |
| `mint_authority_revoked`, `freeze_authority_revoked` | Explicit null RPC authority fields; missing fields are unknown. |
| `category` | Stonkfun quote category: xstock, prestock, custom, collectibles, currencies, leverage. |

Ranking accepts numeric fields only. At most 30 requirements are supported.
`verify_on_chain` defaults to true and adds `initialized_mint == true`.
Set it to false for provider-only screening; explicit RPC conditions still
need RPC evidence. Market enrichment cannot satisfy authority checks.
`max_age_seconds` defaults to 900 and accepts 1–604800. Prefer the provider
update time when exposed; otherwise use retrieval time, which does not prove
the provider refreshed its cache recently. Missing, invalid, future or stale
observations remain unknown. Stonkfun query search has no Jupiter enrichment,
so Jupiter-only fields can be unavailable there.

Jupiter supports `recent`, `toptraded`, `toptrending`, `toporganicscore` feeds;
only ranked feeds accept `--interval 5m|1h|6h|24h`. Stonkfun feeds are `recent`,
`marketCap`, `volume`; query `--sort` accepts `marketCap`, `volume`, `newest`.
Queries reject feed/category/interval. Only Stonkfun supports pagination and
listing categories. Explicit-mint market lookups use one Jupiter batch;
RPC-only criteria skip Jupiter. Configure providers in Growr's root `.env`.

| Bound | Default | Range |
| --- | --- | --- |
| `--candidate-limit` | 50 distinct mints, in discovery order | 1–100 |
| `--scan-limit` | 5 additional mint scans | 0–20 |
| `--top` | 5 reported matches | 1–100 |
| `--page`, `--pages`, `--page-size` | 1, 1, 30 | 1–10000, 1–10, 1–100 |
| `--max-rpc-calls`, `--max-http-calls` | 20, 10 | 0–500, 0–100 |
| `--timeout` | 30 seconds per child | 1–120 |
| `--max-seconds` | 180 seconds for child execution | 1–1800 |

The controller reserves up to four RPC calls per token child and two HTTP
calls per Stonkfun list page; other discovery uses one HTTP call. It retains
reservations after failures and timeouts, and supplies matching child request
caps. `budget.measured` separately reports known attempted requests. Discovery
can stop at the candidate/page cap; RPC verification stops at its own bounds.
Unverified candidates remain unknown when RPC conditions are required.

JSON uses `playbook_version: "1.1"`, `playbook: "token_screen"` and
`screening_version: "1.0"`. `matches` contains the shortlist; `other_matches`,
`unknown`, and `rejected` retain the remaining evaluated candidates.
Each evaluated requirement records `expected`, observed `value`, `outcome`
and source/scope/time evidence. `criteria`, `scope`, `gaps`, `evidence`,
`scans`, and `budget` make decisions reviewable and replayable. Saved inputs
are capped at 10 MiB; criteria files at 64 KiB. On replay, original child
indices refer to `scope.source_scans`; current `scans` is empty.

A usable partial result exits 0, an initial live failure exits 1, and invalid
arguments/files exit 2 with usage on stderr. Always inspect JSON status and
coverage. Zero matches is a valid outcome. The result describes the examined
scope, not the entire token market or a prediction of future returns.

## OpenClaw integration

The separate Growr skills repository contains `growr-discover`,
`growr-screen` and `growr-investigate`. They use the installed `growr`
executable; they do not require `GROWR_ROOT` or `GROWR_PYTHON`.
Skills remain excluded from the Growr repository and distribution.

Each skill requires `growr` on PATH and runs this compatibility check:

```bash
growr doctor --json --min-version 0.3.0 --max-version 0.4.0 \
  --require-cli-schema 2.2 --require-playbook-version 1.1 \
  --require-screening-version 1.0
```

Doctor emits its own `doctor_version: "1.0"` document, with `growr_version`,
`contracts`, available `playbooks`, configuration/key-presence states and
`errors`. It exits 1 on required version/contract mismatches, missing recipe
modules or invalid environment files; otherwise it exits 0. Version minimum
is inclusive and maximum exclusive. It never makes network requests or
prints credential values. Success establishes local compatibility, not live
provider availability. Missing optional API keys do not block offline use.

Clone the skills repository, then merge its absolute root directory into
your OpenClaw configuration. Its root contains the individual skill folders:

```json
{
  "skills": {
    "load": {"extraDirs": ["/absolute/path/to/growr-skills"]}
  }
}
```

The local nested layout can use `/absolute/path/to/growr/skills` instead.
For sandboxed execution, install Growr and supply its configuration inside
the sandbox as well. Host environment settings do not automatically
propagate there. See the official
[skill configuration](https://docs.openclaw.ai/tools/skills-config) and
[skill loading](https://docs.openclaw.ai/tools/skills) documentation.

Check availability with the [OpenClaw skills CLI](https://docs.openclaw.ai/cli/skills):

```bash
openclaw skills list --eligible
openclaw skills info growr-screen
openclaw skills check
```

Release Growr v0.3.0 before publishing the corresponding skills: their
installer targets that Git tag. The skills repository checks the installed
version and contracts independently; each skill folder can be published
separately to ClawHub. No publishing or automatic updates happen inside Growr.

Example prompts: “Find Jupiter candidates named JUP without RPC scans”;
“Screen Stonkfun xstocks with at least $100k token liquidity and a reported
website; rank by 24h volume and verify at most five mints”; “For this mint,
inspect five sampled owners, then compare their shared holdings.” Skills
consume Growr JSON, keep provider text as data, and make missing evidence
explicit. They do not sign transactions, trade, or confirm bundle membership.

## Single Stonkfun token

`token <MINT>` runs the RPC scan with Jupiter and Rugcheck
context. With `--stonk`, the mint, metadata and largest-account RPC checks
still run, while Stonkfun supplies the external context in place of those
two providers.

```bash
python3 growr.py token <MINT> --stonk
python3 growr.py --json token <MINT> --stonk
python3 growr.py --json --include-raw token <MINT> --stonk
```

Stonkfun requires no API key. `STONKS_API_URL` defaults to
`https://www.stonkfun.xyz/api/public/v1`:

| Endpoint | Data |
| --- | --- |
| `/tokens/<MINT>` | Exact token, price, market cap, volume, launch and quote details |
| `/tokens/<MINT>/burns` | Reported burn total and recent events |
| `/tokens/<MINT>/rewards` | Reward currency, distributed/undistributed totals, counts and last payout |
| `STONKS_HOLDERS_API_URL?mint=<MINT>` | Supply, holder count, addresses, balances and completeness |

Holders still use `https://www.stonkfun.xyz/api/token-holders`: the documented
v1 API has no live-holder endpoint. Configure that full URL separately when
using a proxy. An existing `STONKS_API_URL=https://www.stonkfun.xyz/api` is
upgraded automatically to v1. Custom API bases are preserved and must serve
v1-compatible routes and responses.

Each endpoint has separate coverage. Unavailable or malformed data is marked
`failed`; `complete: false` holder data is `partial` and remains available.
A usable RPC report still exits zero when optional Stonkfun context is partial.
The API's `not_found` token response is `no_data`. Normal RPC failures retain their
existing behavior. Jupiter credentials and other market-provider settings are
unused in this mode; `--no-jupiter` and `--no-rugcheck` are redundant with it.

JSON keeps the canonical command and record kind `token`. Provider observations
appear under `records[].metrics.stonks_market`, `stonks_holders`, and
`stonks_burns`, and `stonks_rewards`, with source `stonks` and normalized data under `values`.
RPC observations remain in `facts`. `--include-raw` adds the fetched endpoint
payloads under the same names in `records[].raw` without extra requests.

The console summarizes the exact token and shows the first ten returned
holders. JSON retains every returned holder and recent burn. A reported
holder address is not assumed to be an RPC token account. Base-unit burn
amounts remain decimal strings when supplied; missing amounts are not inferred
from floating-point values. USD values describe historical values at burn time.
V1 exposes `stonks_burns.values.totals` and `recent`; the former unversioned
`buyback_totals`, `reward_totals`, and `all_totals` breakdown is no longer
supplied. Consumers must tolerate these optional groups being absent.

## Stonkfun reward totals and daily comparisons

`token <MINT> --stonk` also retrieves coin-wide reward totals. Reward-mode
coins report the currency they pay, lifetime distributed tokens, reported
undistributed tokens, payout/holder counts, and the last payout time.
Standard-mode coins return `no_data` for rewards; this is not a provider failure.
These amounts describe the coin's distributions, not an individual wallet's earnings.

Save a normal JSON report, then pass it to a later run with `--compare-to`:

```bash
# First observation: retain this file in your reporting pipeline.
python3 growr.py --json token <MINT> --stonk > first.json

# Run later, for example the following day, using a DIFFERENT output file.
python3 growr.py --json token <MINT> --stonk \
  --compare-to first.json > latest.json

# Display the same comparison in the console.
python3 growr.py token <MINT> --stonk --compare-to first.json
```

Replace `<MINT>` with the coin address. `--compare-to` requires `token --stonk`
and a schema 2.2 Growr report with successful, timestamped rewards for the
same mint. A report marked `partial` can still supply a baseline when its
rewards operation succeeded. Older reports without reward snapshots cannot.
`--include-raw` is not needed. Invalid files fail before network clients are created.

**Never redirect output into the input snapshot file.** The shell truncates
redirected output before Growr can read it. Growr only reads the supplied
file; it does not create a database, update history, or schedule future runs.
Your pipeline controls retention and scheduling.

The calculation uses cumulative **raw reward-token units** and Stonkfun's
`meta.generatedAt`, not the CLI run timestamp or the token's price:

```text
interval rewards = current distributed total − previous distributed total
normalized daily rate = interval rewards × 86400 / elapsed seconds
```

For example, 2 reward tokens distributed over 12 hours produce an observed
interval total of 2 and a normalized rate of 4 tokens per 24 hours. That rate
is not a measured calendar-day payout or a forecast. Cached timestamps,
missing timestamps, changed reward mint/decimals, and decreasing counters
make the comparison unavailable instead of producing misleading amounts.
Current scan data remains available with failed comparison coverage and exit 0.

JSON schema 2.2 adds these token metric groups:

| Group | Source | Values |
| --- | --- | --- |
| `records[].metrics.stonks_rewards` | `stonks` | Reward mint/symbol/decimals, `distributed_raw`, `distributed_tokens`, `undistributed_raw`, `undistributed_tokens`, reported counts, `last_payout_at`, `provider_generated_at` |
| `records[].metrics.reward_comparison` | `growr` | Reward identity, `previous_generated_at`, `current_generated_at`, `elapsed_seconds`, `distributed_delta_raw`, `distributed_delta_tokens`, `normalized_daily_tokens` |

Values are under each group's `values` key. Raw quantities are integer strings;
token amounts are exact decimal strings. The daily division uses 28 significant
digits. Missing optional measurements remain null, and genuine zero stays zero.
A successful comparison appears in the second group; unavailable comparisons
omit it and explain the problem in coverage. Neither group becomes an RPC fact.
`request.options.compare_rewards` records whether comparison was requested,
without revealing the local filename. `--include-raw` preserves the current
reward API envelope; it does not copy the baseline file into the output.

No additional reward requests are made by search, list, or ordinary token scans.

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
All modes fetch one `/tokens` page. `recent` maps to `sort=newest`, browsing
newest tokens with live platform pools instead of the former recent-launch
window. Defaults remain `--page 1 --page-size 30`; page must be positive and
page size must be 1–100. All modes support pagination, `--json` and `--on-chain`.

Use `--category` to filter any Stonks listing by `xstock`, `prestock`, `custom`,
`collectibles`, `currencies`, or `leverage`. The API performs category filtering
alongside sorting and pagination. Omitting it requests all categories.

```bash
python growr.py list stonks --category xstock --page 2 --page-size 20
```

Platform results retain Stonks' ordering. Their tables show the returned page, page size,
total results, page count, and row numbers across pages. A Stonks market-cap or 24-hour
volume column shows the ranking value separately from enriched metrics, which can differ.
JSON preserves returned pagination and one normalized record per pool. With
`--include-raw`, `raw.discovery` also retains the original `data`/`meta` envelope. Only returned `data.tokens` enter the rankings.
An empty page is `no_data`; invalid requests reported by Stonks exit nonzero.

The default view shows market and risk tables for every returned launch.
Jupiter supplies token price, liquidity, holder counts, audit indicators,
developer information, organic score, and trading statistics. Stonks launch
metadata, quote assets, graduation status, and reported transfer tax remain.
Without `JUPITER_API_KEY`, Stonks discovery still runs and enrichment coverage
shows `not_configured`.

Results are joined by exact mint address, batching up to 100 unique mints.
Price, market cap and FDV prefer available Jupiter values, then Stonks values.
Liquidity is Jupiter's token-level measurement; no individual-pool liquidity
is inferred. Table cells identify sources as J (Jupiter), S (Stonks), or R
(RPC); `—` means unknown, not zero.

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

`STONKS_API_URL` defaults to `https://www.stonkfun.xyz/api/public/v1`.
The [public API documentation](https://www.stonkfun.xyz/developers) specifies
300 read requests per minute per IP. Growr does not retry automatically;
HTTP 429 failures report the server's `Retry-After` delay when valid. Scheduled
callers should respect that delay before another invocation.

## Jupiter discovery

`list jupiter` fetches one recent-pools response. Ranked feeds provide
trading and organic-score discovery without requiring a query.
Jupiter's recent feed reflects first pool creation, not token mint creation.

```bash
python3 growr.py list jupiter
python3 growr.py list jupiter --jupiter-search toptraded --interval 1h --limit 20
python3 growr.py list jupiter --jupiter-search toptrending
python3 growr.py list jupiter --jupiter-search toporganicscore
```

Ranked feeds accept `--interval` (`5m`, `1h`, `6h`, `24h`; default `24h`)
and `--limit` (1–100; default 50). Recent listings reject these options.
No automatic pagination or repeat market lookup occurs: discovery already
returns token information. Use `search jupiter <QUERY>` for query lookup.

The [Jupiter Tokens API](https://developers.jup.ag/docs/tokens/token-information)
documents these endpoints. Configure `JUPITER_API_KEY` before Jupiter listings;
a missing key fails before network clients are created. Direct RPC scans and
Stonks discovery can still run without that optional enrichment credential.

Use `growr.py list <stonks|jupiter> [options]`. `list --stonk` remains supported.
`list --help` explains both providers and examples. A missing provider displays
that help on stderr and exits 2; JSON mode emits a structured argument error.
Stonks pagination/category flags and Jupiter search flags cannot be mixed.

## Token search

`search <jupiter|stonks> <QUERY>` makes one lookup through the selected
provider. It returns candidates for a person or consuming agent to select.
`--on-chain` is not accepted; pass the selected mint to a separate `token`
command. Both providers support console output, `--json`, and `--include-raw`.
Global output flags go before `search`.

### Jupiter

`search jupiter <QUERY>` finds Solana token candidates by name, symbol or mint
using Jupiter's `/tokens/v2/search` endpoint. Configure `JUPITER_API_KEY`
(or `JUP_API_KEY`); the command reads it from the environment. A missing key
fails before any network clients are created.

```bash
python3 growr.py search jupiter JUP
python3 growr.py search jupiter "Wrapped SOL"
python3 growr.py --json search jupiter <MINT>
python3 growr.py --json --include-raw search jupiter JUP
python3 growr.py --json search jupiter "<MINT_1>,<MINT_2>"

# After a person or agent selects a returned mint:
python3 growr.py --json token <MINT>
```

Names and symbols can return multiple candidates. Results preserve Jupiter's
order and include mint addresses, names, symbols, available market data and
social links. Mint queries retain only exact `id` matches. Comma-separated
queries accept up to 100 mint addresses; multiple names are not supported.

Jupiter search makes one lookup without RPC, Rugcheck or Stonkfun requests.
It does not select or scan a result automatically. `--on-chain`, feed ranking,
interval, limit, pagination and category flags are not accepted by `search jupiter`.
Choose an explicit mint for a subsequent `token` command. `search --help`
shows examples; missing provider/query arguments also show that help.

JSON uses `request.command: "search"`, with the provider and normalized query
in `request.options`. Both `request.target` and `request.rpc` are null.
Results use the existing `token_discovery` records; `identity.mint` is the
address to pass to `token`. Each `on_chain` field is null. An empty match
returns `no_data` and exit code 0; provider failures return a structured error
and exit code 1. `--include-raw` retains the fetched response without extra calls.

The former `list jupiter --query <QUERY>` invocation has moved to
`search jupiter <QUERY>`. `list` now handles recent and ranked feeds.

### Stonks

`search stonks <QUERY>` sends the text as `q` to `/tokens`, using
`STONKS_API_URL`. It requires no API key and does not call Jupiter, RPC,
Rugcheck, token-holders or burns endpoints. Unused provider credentials and
URLs do not affect this command.

```bash
python3 growr.py search stonks te
python3 growr.py --json search stonks "test token"
python3 growr.py search stonks te --sort volume --page 2 --page-size 30
python3 growr.py --json --include-raw search stonks te

# Analyze a selected mint with RPC and Stonkfun context:
python3 growr.py --json token <MINT> --stonk
```

| Option | Values | Default |
| --- | --- | --- |
| `--sort` | `marketCap`, `volume`, `newest` | `marketCap` |
| `--page` | Positive integer | `1` |
| `--page-size` | Integer, 1–100 | `30` |

These options apply only to Stonks search. The command fetches one page;
Stonkfun controls query matching and ordering. Growr retains every returned
pool, including separate pools for the same mint, without local filtering,
ranking or automatic pagination. Blank queries fail before network calls.
Category filters remain available on Stonks `list` commands.

Console results include names, full mint addresses, available market values,
social links and returned pagination. JSON uses the existing schema 2.2
`pool` records, `identity.mint` and `identity.pool`, and Stonks-sourced
measurements in `metrics.market`. `request.options` includes the query, sort,
page and page size; top-level `pagination` reflects the provider's response.
`request.rpc` and each `on_chain` field are null. An empty page is `no_data`;
HTTP or malformed-response failures are structured errors. With
`--include-raw`, `raw.discovery` retains the original `data`/`meta` envelope. Only `data.tokens` enter the result list.

## Social presence

Jupiter token scans, both search providers and both listing providers include
a presence score and website/social links with source attribution. The score uses fetched links:

- A project website: **40 points**.
- A first social platform: **40 points**.
- A second distinct social platform: **20 points**.

The maximum is 100. Duplicate links and repeated providers add no points;
Twitter and X count as one platform. Links are validated HTTP(S) URLs;
bare handles, credentials, malformed ports, embedded whitespace, invalid
escapes, bare social homepages and generic Stonks pages are excluded.
Valid internationalized URLs are normalized to ASCII URIs. Links are not
visited: presence does not establish authenticity, engagement or safety.
Zero means no valid links observed, with retrieval failures shown in coverage.

Jupiter contributes its explicit website, Twitter, Telegram, Discord,
Instagram and TikTok fields when present. Stonks listings merge their own
links with the exact-mint Jupiter result. Stonks search uses only links
returned by Stonkfun. All links appear with sources in
console output and `records[].social` in JSON. RPC facts and risk scores
remain separate. With Jupiter disabled, a direct token's social field is null.
The Stonkfun-only token mode continues to expose its platform reports.

## Optional listing verification

Both providers accept `--on-chain`:

```bash
python3 growr.py --json list jupiter --jupiter-search toptraded --limit 5 --on-chain
python3 growr.py --json list stonks --on-chain
```

Each unique Solana mint is scanned once with at most two workers. Missing or
invalid mint addresses and failed scans produce coverage gaps without
discarding other results. JSON includes nested `on_chain` records for successful
scans; console output includes an observations table. Verification performs
only RPC reads. Listings without `--on-chain` make no RPC requests.

## JSON 2.2 migration

Consumers should support `schema_version == "2.2"`. This additive version
introduces the reward metric groups and `request.options.compare_rewards`.
Reward amounts use decimal strings, as described above. Existing scan, list,
and search record layouts remain intact. Version 2.1 introduced `search`;
query text remains in search options, while list options describe feeds.
Direct token market data
is in `records[].metrics.jupiter.values`, including price, token liquidity,
audit, activity and first-pool information. Social evidence is in
`records[].social`, outside RPC `facts`. Jupiter discovery uses the same
Jupiter metric group and `token_discovery` kind; its `identity.mint` comes
from the provider's `id`. Stonks keeps pool identities and sourced
`market`, `risk` and `activity` groups, with token-level liquidity only.
The envelope, exit-code rules, raw opt-in and RPC fact layout remain consistent.

## Architecture

The CLI constructs provider clients and passes them to scan, discovery, and
enrichment workflows. Each integration owns its API requests and response
translation. Pure analysis functions handle metrics and risk rules; renderers
format completed reports. Application modules live in `growr_cli/`.

```text
growr.py
  settings.py     dotenv-loaded application settings and RPC selection
  solana/         RPC, SPL decoding, metadata, and holder reads
  integrations/   Jupiter, Rugcheck, Stonks, shared HTTP
  analysis/       pure metric, social-presence, and risk rules
  scanners/       separate token, token-account, and wallet workflows
  searchers/      Stonks and Jupiter discovery workflows
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
- Jupiter and Rugcheck are optional context. Their failure does not make a valid on-chain scan fail.
- Transaction interpretation covers standard System/token actions in legacy/v0 transactions. Protocol-specific swaps, recursive funding graphs and bundle confirmation are not implemented.

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
python3 scripts/live_smoke.py --mint <MINT> --stonk --scans-only
```

The harness uses configured services, makes at most 30 outbound requests
(including redirects), applies socket timeouts of at most 10 seconds, and stops
after 120 seconds. It performs no automatic retries and verifies at most one
listing result per provider. Output contains schema-checked coverage summaries,
not provider payloads. Exit 1 means a check was partial, failed, unverified, or
hit a budget; it must not be interpreted as a successful readiness check.

## License

growr is licensed under the [MIT License](LICENSE).
