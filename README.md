# LedgerSync (Free)

Previews reconciliation of your local trade/position/equity records against
Interactive Brokers' Flex Query reporting data -- built out of real
production experience running a live, multi-account automated trading
operation on IBKR, after hitting the exact gap this tool closes.

## The problem this solves

IBKR's live TWS/Gateway API is great for placing orders and streaming
quotes, but it is not a reliable system of record for what actually
happened to those orders. In particular: **execution and commission-report
data does not reliably survive a client disconnect.**

If your process connects, places an order, and disconnects before that
order fills -- a common pattern for anything that places a day order near
the open and then goes offline until it's needed again -- the real fill
price, commission, and realized P&L for that trade can simply be gone from
anything the live API will give you by the time you reconnect.

IBKR's own answer to this is the **Flex Web Service** -- a separate,
asynchronous, purpose-built reporting API that is independent of any
client's connect state and retains execution history for a real window.
LedgerSync is the plumbing to make that usable in practice: it polls Flex
Query reports, matches your pending items against real fills (handling
split fills and disambiguating duplicate candidates with a documented,
printed heuristic), and tells you exactly what it would correct.

## Free vs Pro

| | LedgerSync (Free) | LedgerSync (Pro) |
|---|---|---|
| Match pending commissions/closes against Flex Query | Yes | Yes |
| Print every match found, with real fill data | Yes | Yes |
| Split-fill aggregation, duplicate-candidate heuristic | Yes | Yes |
| **Write corrections back to your state files** | **No -- not implemented in this package** | Yes |
| Optional live position cross-check (read-only, needs `ib_insync`) | No | Yes |

This package can only ever preview. There is no `--dry-run` flag because
there is nothing else it does -- the write-back code that applies a
correction to your `positions.json`/`equity.json`/`trades.csv` doesn't
exist in this codebase at all. [LedgerSync (Pro)](https://algovigil.com/ledgersync)
adds that, plus the optional live-position cross-check diagnostic.

## What this is not

LedgerSync does not place trades, manage risk, or touch your live orders.
It only reads Flex Query reports and your own local state files. This Free
build additionally never writes anything -- not even to your local files.

## Install

```bash
pip install -e .
```

## Configure

Credentials are never hardcoded and never default to anything -- LedgerSync
raises a clear error if a required value is missing.

```bash
export IBKR_ACCOUNT_ID="U1234567"
export IBKR_FLEX_TOKEN="your-flex-web-service-token"
export IBKR_FLEX_QUERY_ID="your-flex-query-id"
```

or via a JSON config file (environment variables take precedence):

```bash
cp config.example.json config.json
```

The Flex Query itself needs to be created in IBKR's Account Management
portal as an **Activity Flex Query**, with a **Trades** section, period set
to something like "Last 30 Calendar Days", and all of these fields ticked:
`symbol`, `dateTime`, `quantity`, `tradePrice`, `ibCommission`,
`fifoPnlRealized`, `buySell`, `ibOrderID`, `ibExecID`.

Before relying on a new token/query, validate it:

```bash
python -m diagnostics.flex_check --token YOUR_TOKEN --query-id YOUR_QUERY_ID
```

## State files

LedgerSync reads a small set of JSON files in your configured `state_dir`
(default `./state`) -- these are **your** files, LedgerSync just reads them:

| File | Purpose |
|---|---|
| `pending_commissions.json` | Queue of trades awaiting confirmed commission data: `{"pending": [{"ticker", "side", "qty", "orderId", "attempts"}, ...]}` |
| `pending_closes.json` | Queue of positions detected closed broker-side but awaiting confirmed exit price/P&L -- write to this via `ledgersync.pending_closes.record_pending_close()` |

## Run

```bash
ledgersync resolve-commissions --config config.json
ledgersync resolve-closes --config config.json
ledgersync resolve-all --config config.json
```

Typical output:

```
Fetching Flex Query data (this can take ~10-30s) ...
Flex Query returned 14 total fill(s) across all symbols/orders.
  [NVDA] qty=164 entry_time=2026-10-12T21:31:04 -> MATCHED SELL 20261012;213815
    avg_price=118.2340 fifoPnlRealized=212.55 (3 fill legs)

3/3 would resolve. PREVIEW ONLY -- nothing written. Upgrade to LedgerSync
(Pro) to apply these corrections to your ledgers: https://algovigil.com/ledgersync
```

## Design notes / known limitations

- **Matching is heuristic, not guaranteed**, when multiple candidates share
  the same `(symbol, side, qty)`. It's a documented, printed, newest-first
  heuristic -- sanity-check a first run against a system you trust.
- **No streaming / webhook support.** This is a pull-based, run-on-a-schedule
  tool, matching how Flex Query itself works.
- Example numbers in this README are synthetic.

## License

MIT -- see [LICENSE.md](LICENSE.md). Genuinely open source: read the code,
modify it, self-host it. The write-back capability and the live-position
cross-check are LedgerSync (Pro) only, not a config flag you can flip on
here.
