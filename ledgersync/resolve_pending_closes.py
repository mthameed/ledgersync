"""Standalone position-close reconciliation (Free) -- matches a pending-closes
queue against real Flex Query SELL fills and prints what it finds.

Free tier: preview only, same as resolve_pending_commissions.py in this
package -- no code path here writes a correction to equity.json or
trades.csv. LedgerSync (Pro) adds the real write-back.

Usage (via the CLI):
    ledgersync resolve-closes --config config.json
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
    """Matches pending closes against Flex SELL fills by (symbol, quantity),
    aggregating split fills by (symbol, orderId) -- same heuristic as
    LedgerSync (Pro)'s version. Prints every match; never writes anything."""
    state_dir = Path(state_dir)
    pending = _load_json(state_dir / "pending_closes.json").get("pending", [])
    if not pending:
        print("No pending close items.")
        return

    print("Fetching Flex Query data (this can take ~10-30s) ...")
    trades = fetch_trades(token=token, query_id=query_id)
    print(f"Flex Query returned {len(trades)} total fill(s) across all symbols/orders.")

    groups: dict[str, dict[int, list[FlexTrade]]] = {}
    for t in trades:
        if t.buy_sell != "SELL":
            continue
        groups.setdefault(t.symbol, {}).setdefault(t.order_id, []).append(t)
    for by_order in groups.values():
        for fills in by_order.values():
            fills.sort(key=lambda t: t.date_time)

    def _order_qty(fills: list[FlexTrade]) -> float:
        return sum(abs(f.quantity) for f in fills)

    pending_sorted = sorted(pending, key=lambda it: it.get("attempts", 0))

    resolved_count = 0
    for item in pending_sorted:
        ticker, qty = item["ticker"], item["qty"]
        by_order = groups.get(ticker, {})
        candidates = sorted(by_order.items(), key=lambda kv: kv[1][-1].date_time, reverse=True)
        match_fills = next((fills for _, fills in candidates if _order_qty(fills) == qty), None)

        if match_fills is None:
            print(f"  [{ticker}] qty={qty} entry_time={item.get('entry_time')} "
                  f"-> no matching Flex SELL found.")
            continue

        resolved_count += 1
        real_pnl = sum(f.fifo_pnl_realized for f in match_fills)
        exit_price = sum(f.trade_price * abs(f.quantity) for f in match_fills) / qty
        last_fill_time = match_fills[-1].date_time
        n_legs = len(match_fills)
        print(f"  [{ticker}] qty={qty} entry_time={item.get('entry_time')} -> MATCHED SELL "
              f"{last_fill_time} avg_price={exit_price:.4f} fifoPnlRealized={real_pnl:.2f} "
              f"({n_legs} fill leg{'s' if n_legs > 1 else ''})")

    print(f"\n{resolved_count}/{len(pending)} would resolve. "
          f"PREVIEW ONLY -- nothing written. Upgrade to LedgerSync (Pro) to apply "
          f"these corrections to your ledgers: https://algovigil.com/ledgersync")
