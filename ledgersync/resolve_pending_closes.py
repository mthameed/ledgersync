"""Standalone position-close reconciliation -- resolves a pending-closes
queue (positions your own reconcile logic detected as closed broker-side,
but couldn't determine real P&L for via the live API) against real Flex
Query data. Same architecture and reasoning as
resolve_pending_commissions.py, applied to full trade closes instead of
just commissions -- see pending_closes.py's docstring for the underlying
gap this resolves.

Deliberately decoupled from your live trading process's own
connect/trade/disconnect cycle -- run this manually or on a schedule,
whenever there's a backlog.

Usage (via the CLI):
    ledgersync resolve-closes --config config.json
    ledgersync resolve-closes --config config.json --dry-run
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .flex_query import fetch_trades, FlexTrade
from .trade_log import append_trade


def _load_json(path: Path) -> dict:
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


def _save_json(path: Path, data: dict) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def resolve(state_dir: Path, token: str, query_id: str, dry_run: bool = False) -> None:
    """Matches pending closes against Flex SELL fills by (symbol,
    quantity), newest-unclaimed-first -- same disambiguation heuristic as
    resolve_pending_commissions.py, same caveat: not a certainty, sanity
    check the printed match's date against the pending item's recorded
    entry_time before trusting it blindly."""
    state_dir = Path(state_dir)
    pending_path = state_dir / "pending_closes.json"
    equity_path = state_dir / "equity.json"

    pending = _load_json(pending_path).get("pending", [])
    if not pending:
        print("No pending close items.")
        return

    equity = _load_json(equity_path)

    print("Fetching Flex Query data (this can take ~10-30s) ...")
    trades = fetch_trades(token=token, query_id=query_id)
    print(f"Flex Query returned {len(trades)} total fill(s) across all symbols/orders.")

    # Group unclaimed SELL fills by (symbol, orderId), newest first. Real
    # IBKR orders routinely fill as several separate execution rows sharing
    # one orderId -- matching against a single row's raw quantity silently
    # misses every split-fill close and reports "no matching Flex SELL
    # found" for what is actually a real, unambiguous exit.
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

    still_pending = []
    resolved_count = 0
    for item in pending_sorted:
        ticker, qty = item["ticker"], item["qty"]
        by_order = groups.get(ticker, {})
        # Newest-unclaimed-first, same disambiguation heuristic as the
        # commission resolver -- just applied to whole orders (by their
        # last fill's time) instead of individual rows.
        candidates = sorted(by_order.items(), key=lambda kv: kv[1][-1].date_time, reverse=True)
        match_order_id, match_fills = next(
            ((oid, fills) for oid, fills in candidates if _order_qty(fills) == qty), (None, None))

        if match_fills is None:
            item["attempts"] = item.get("attempts", 0) + 1
            still_pending.append(item)
            print(f"  [{ticker}] qty={qty} entry_time={item.get('entry_time')} "
                  f"-> no matching Flex SELL found (attempt {item['attempts']}).")
            continue

        del by_order[match_order_id]
        resolved_count += 1
        real_pnl = sum(f.fifo_pnl_realized for f in match_fills)
        total_commission = sum(abs(f.commission) for f in match_fills)
        # Quantity-weighted average fill price across the split -- the real
        # exit price, not any single leg's.
        exit_price = sum(f.trade_price * abs(f.quantity) for f in match_fills) / qty
        last_fill_time = match_fills[-1].date_time
        n_legs = len(match_fills)
        print(f"  [{ticker}] qty={qty} entry_time={item.get('entry_time')} -> MATCHED SELL "
              f"{last_fill_time} avg_price={exit_price:.4f} fifoPnlRealized={real_pnl:.2f} "
              f"(real ibOrderID={match_order_id}, {n_legs} fill leg{'s' if n_legs > 1 else ''})")

        if dry_run:
            continue

        entry_price = item.get("entry_price") or exit_price
        r_dist = item.get("r_dist") or 0.0
        r_multiple = (real_pnl / qty / r_dist) if r_dist else 0.0

        note = (
            f"Flex-resolved close (pending_closes.json), matched real SELL "
            f"{last_fill_time} ibOrderID={match_order_id} ({n_legs} fill leg{'s' if n_legs > 1 else ''}, "
            f"aggregated). pnl is IBKR's own fifoPnlRealized (commission-inclusive, FIFO-matched "
            f"across this account's full trading history for this symbol), summed across the split."
        )
        append_trade(state_dir, datetime.now(timezone.utc), ticker, "LONG", entry_price, exit_price,
                     qty, real_pnl, r_multiple, "reconcile_correction", note=note,
                     commission=total_commission)

        cost_basis = item.get("cost_basis")
        if cost_basis is not None:
            # Ledgers that track a per-position cost basis: credit the
            # freed-up cost basis plus the realized P&L back into cash.
            equity["cash"] = equity.get("cash", 0.0) + cost_basis + real_pnl
        else:
            # Ledgers that track running equity/P&L directly instead of a
            # per-position cost basis -- credit realized P&L straight in.
            equity["equity"] = equity.get("equity", 0.0) + real_pnl

    if not dry_run:
        _save_json(pending_path, {"pending": still_pending})
        equity["updated_at"] = datetime.now(timezone.utc).isoformat()
        _save_json(equity_path, equity)

    print(f"\n{resolved_count}/{len(pending)} resolved, "
          f"{len(still_pending)} still pending."
          f"{' (dry run -- nothing written)' if dry_run else ''}")
