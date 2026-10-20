# LedgerSync

Reconciles your local trade/position/equity records against Interactive
Brokers' Flex Query reporting data -- built out of real production
experience running a live, multi-account automated trading operation on
IBKR, after hitting the exact gap this tool closes.

## The problem this solves

IBKR's live TWS/Gateway API is great for placing orders and streaming
quotes, but it is not a reliable system of record for what actually
happened to those orders. In particular: **execution and commission-report
data does not reliably survive a client disconnect.**

If your process connects, places an order, and disconnects before that
order fills -- a common pattern for anything that places a day order near
the open and then goes offline until it's needed again -- the real fill
price, commission, and realized P&L for that trade can simply be gone from
anything the live API will give you by the time you reconnect. This isn't
a hypothetical edge case; it's a real failure mode that shows up constantly
in any live algorithmic setup that doesn't stay connected 24/7.

IBKR's own answer to this is the **Flex Web Service** -- a separate,
asynchronous, purpose-built reporting API that is independent of any
client's connect state and retains execution history for a real window
(weeks, depending on how you configure the query). It is not a live
trading API: you submit a request, poll until the report is ready, and
parse an XML document of trade rows. It is, however, the only place this
data reliably still exists once the live API has lost it.

LedgerSync is the plumbing to make that usable in practice:

1. **Poll Flex Query reports** (`ledgersync/flex_query.py`) -- handles the
   asynchronous SendRequest -> GetStatement flow, including IBKR's
   occasional regional-host redirect quirk.
2. **Match a local "pending" queue against real fills** -- when your own
   bookkeeping knows a trade happened (an order went out, or a position
   you were tracking disappeared broker-side) but doesn't yet have
   confirmed commission/P&L for it, LedgerSync matches that pending item
   against the Flex report by symbol, side, and quantity -- there is
   usually no shared order id to join on, because the id your own trading
   code assigns and IBKR's permanent order id are two unrelated numbers.
3. **Handle the real-world mess**, not just the clean case:
   - **Split fills.** A single order routinely arrives as several separate
     execution rows (e.g. a 223-share order filling as 100+100+23).
     LedgerSync groups fills by `(symbol, orderId)` and aggregates them --
     matching against one row's raw quantity silently misses every
     split-fill close.
   - **Duplicate-candidate disambiguation.** If two unclaimed fills match
     the same `(symbol, side, qty)` -- e.g. two separate same-size buys of
     the same stock days apart -- there's no way to know for certain which
     one a given pending item corresponds to. LedgerSync resolves this with
     a documented, printed heuristic (newest pending item claims the most
     recent unclaimed match) rather than silently guessing, so you can
     sanity-check it before trusting it.
   - **Quantity-weighted exit pricing** across a split close, and crediting
     IBKR's own `fifoPnlRealized` (its authoritative, commission-inclusive,
     FIFO-matched realized P&L) rather than recomputing P&L yourself from
     partial information.
4. **Reconcile local state against broker truth** -- credit the resolved
   commission/P&L back into your local position and equity ledgers, log a
   proper trade record, and clear the item out of the pending queue.
5. **Cross-check positions directly** (`diagnostics/cross_check_positions.py`)
   -- a separate, read-only check against IBKR's live position list, for
   catching drift that isn't about commissions or closes at all.

## What this is not

LedgerSync does not place trades, manage risk, or touch your live orders.
It only reads Flex Query reports and your own local state files, and
writes corrections back to your own local state files. The only live
connection anywhere in this package is the optional position cross-check
diagnostic, which is read-only.

## Install

```bash
pip install -e .
# or, to also use the live-position diagnostic:
pip install -e ".[diagnostics]"
```

## Configure

Credentials are never hardcoded and never default to anything -- LedgerSync
raises a clear error if a required value is missing. Provide them either as
environment variables:

```bash
export IBKR_ACCOUNT_ID="U1234567"
export IBKR_FLEX_TOKEN="your-flex-web-service-token"
export IBKR_FLEX_QUERY_ID="your-flex-query-id"
```

or via a JSON config file (environment variables take precedence over this
if both are set):

```bash
cp config.example.json config.json
```

```json
{
  "account_id": "YOUR_ACCOUNT_ID_HERE",
  "flex_token": "YOUR_FLEX_TOKEN_HERE",
  "flex_query_id": "YOUR_FLEX_QUERY_ID_HERE",
  "state_dir": "state"
}
```

The Flex Query itself needs to be created in IBKR's Account Management
portal as an **Activity Flex Query**, with a **Trades** section, period set
to something like "Last 30 Calendar Days", and all of these fields ticked:
`symbol`, `dateTime`, `quantity`, `tradePrice`, `ibCommission`,
`fifoPnlRealized`, `buySell`, `ibOrderID`, `ibExecID`. A **Trade
Confirmation**-type query looks similar but its period can be locked to
"Today" on some accounts, which makes it useless for anything beyond the
current calendar day -- use the Activity type.

Before relying on a new token/query, validate it:

```bash
python -m diagnostics.flex_check --token YOUR_TOKEN --query-id YOUR_QUERY_ID
```

This checks the thing that actually breaks silently: a query with the
right type and period but the wrong fields ticked looks fine in the portal
and fails later, mid-reconciliation, as a `TypeError` on `float(None)`.

## State files

LedgerSync reads and writes a small set of JSON/CSV files in your
configured `state_dir` (default `./state`). These are **your** files --
LedgerSync doesn't create a trading system around them, it just reconciles
them against Flex Query:

| File | Purpose |
|---|---|
| `pending_commissions.json` | Queue of trades awaiting confirmed commission data: `{"pending": [{"ticker", "side", "qty", "orderId", "attempts"}, ...]}` |
| `pending_closes.json` | Queue of positions detected closed broker-side but awaiting confirmed exit price/P&L |
| `positions.json` | Your local open-position record: `{"positions": {"TICKER": {"qty", "cost_basis", ...}}}` |
| `equity.json` | Your local equity/cash ledger |
| `trades.csv` | Append-only closed-trade log LedgerSync writes corrections into |

## Run

```bash
ledgersync resolve-commissions --config config.json
ledgersync resolve-closes --config config.json
ledgersync resolve-all --config config.json
```

Try it risk-free first -- prints every match it finds without writing
anything:

```bash
ledgersync resolve-all --config config.json --dry-run
```

Typical output:

```
Fetching Flex Query data (this can take ~10-30s) ...
Flex Query returned 14 total fill(s) across all symbols/orders.
  [NVDA] qty=164 entry_time=2026-10-12T21:31:04 -> MATCHED SELL 20261012;213815
    avg_price=118.2340 fifoPnlRealized=212.55 (real ibOrderID=730566271, 3 fill legs)

3/3 resolved, 0 still pending.
```

Then cross-check live positions directly (optional, needs `ib_insync` and a
running TWS/Gateway connection):

```bash
python -m diagnostics.cross_check_positions --port 7497 --client-id 99 \
    --positions-file state/positions.json
```

## Design notes / known limitations

- **Matching is heuristic, not guaranteed**, when multiple candidates share
  the same `(symbol, side, qty)`. It's a documented, printed, newest-first
  heuristic -- not a silent guess -- but sanity-check the first run against
  a system you trust before relying on it unattended.
- **Single-account cross-check only.** The position diagnostic checks one
  broker account against one local state file. If you run several accounts,
  run it once per account; summing several local books against one shared
  broker account is a materially weaker check and isn't implemented here.
- **No streaming / webhook support.** This is a pull-based, run-on-a-schedule
  tool, matching how Flex Query itself works (an asynchronous report, not a
  live feed).
- Example numbers in this README are synthetic.

## License

MIT -- see [LICENSE](LICENSE).
