"""Standalone commission reconciliation (Free) -- matches a pending-commissions
queue against real Flex Query data and prints what it finds.

This is the Free tier: it can only ever PREVIEW matches. There is no code
path anywhere in this module that writes a correction back to your state
files -- not a flag, a permanently absent capability. See resolve() below:
it takes no `dry_run` parameter because there is nothing to gate.
LedgerSync (Pro) adds the real write-back that applies these corrections to
your positions/equity ledgers.

Usage (via the CLI):
    ledgersync resolve-commissions --config config.json
"""
from __future__ import annotations

import json
from pathlib import Path

from .flex_query import fetch_trades, FlexTrade


def _load_json(path: Path) -> dict:
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


def resolve(state_dir: Path, token: str, query_id: str) -> None:
    """Matches pending items against Flex data by (symbol, side, quantity),
    NOT by order id -- see LedgerSync (Pro)'s version of this module for why.
    Same newest-first disambiguation heuristic. Prints every match found;
    never writes anything, by construction."""
    state_dir = Path(state_dir)
    pending = _load_json(state_dir / "pending_commissions.json").get("pending", [])
    if not pending:
        print("No pending commission items.")
        return

    print("Fetching Flex Query data (this can take ~10-30s) ...")
    trades = fetch_trades(token=token, query_id=query_id)
    print(f"Flex Query returned {len(trades)} total fill(s) across all symbols/orders.")

    pools: dict[tuple[str, str], list[FlexTrade]] = {}
    for t in trades:
        key = (t.symbol, "entry" if t.buy_sell == "BUY" else "exit")
        pools.setdefault(key, []).append(t)
    for lst in pools.values():
        lst.sort(key=lambda t: t.date_time, reverse=True)

    pending_sorted = sorted(pending, key=lambda it: it.get("attempts", 0))

    resolved_count = 0
    for item in pending_sorted:
        ticker, side, qty = item["ticker"], item["side"], item["qty"]
        pool = pools.get((ticker, side), [])
        match = next((t for t in pool if abs(t.quantity) == qty), None)

        if match is None:
            print(f"  [{ticker}] side={side} qty={qty} -> no matching Flex trade found.")
            continue

        pool.remove(match)
        resolved_count += 1
        print(f"  [{ticker}] side={side} qty={qty} -> MATCHED {match.date_time} "
              f"price={match.trade_price} commission=${match.commission:.4f} "
              f"fifoPnlRealized={match.fifo_pnl_realized:.2f} (real ibOrderID={match.order_id})")

    print(f"\n{resolved_count}/{len(pending)} would resolve. "
          f"PREVIEW ONLY -- nothing written. Upgrade to LedgerSync (Pro) to apply "
          f"these corrections to your ledgers: https://algovigil.com/ledgersync")
