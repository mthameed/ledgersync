"""Standalone commission reconciliation -- resolves a pending-commissions
queue against real Flex Query data, instead of depending on the live
TWS/Gateway API (see flex_query.py's docstring for why that API can't be
trusted for this).

Deliberately decoupled from your live trading process's own
connect/trade/disconnect cycle -- run this manually or on a schedule,
whenever there's a backlog to clear.

Usage (via the CLI):
    ledgersync resolve-commissions --config config.json
    ledgersync resolve-commissions --config config.json --dry-run
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
    """Matches pending items against Flex data by (symbol, side, quantity),
    NOT by order id. In practice, whatever order id your own trading code
    assigns (e.g. a client library's internal request counter) has no
    relationship to IBKR's real, permanent order identifier that shows up
    in Flex Query -- there is no shared id to join on at all.

    Disambiguation when multiple Flex trades share the same (symbol, side,
    qty) -- e.g. two separate buys of the same size, days apart: pending
    items are processed newest-first (lowest "attempts" = created most
    recently), each claiming the MOST RECENT still-unclaimed Flex trade
    matching its qty. This is a heuristic, not a certainty -- check the
    printed match's date against what you expected before trusting it
    blindly on a first run."""
    state_dir = Path(state_dir)
    pending_path = state_dir / "pending_commissions.json"
    positions_path = state_dir / "positions.json"
    equity_path = state_dir / "equity.json"

    pending = _load_json(pending_path).get("pending", [])
    if not pending:
        print("No pending commission items.")
        return

    positions = _load_json(positions_path)
    equity = _load_json(equity_path)

    print("Fetching Flex Query data (this can take ~10-30s) ...")
    trades = fetch_trades(token=token, query_id=query_id)
    print(f"Flex Query returned {len(trades)} total fill(s) across all symbols/orders.")

    # Pool of unclaimed Flex trades per (symbol, side), newest first.
    pools: dict[tuple[str, str], list[FlexTrade]] = {}
    for t in trades:
        key = (t.symbol, "entry" if t.buy_sell == "BUY" else "exit")
        pools.setdefault(key, []).append(t)
    for lst in pools.values():
        lst.sort(key=lambda t: t.date_time, reverse=True)

    # Newest pending items first (lowest attempts = created most recently).
    pending_sorted = sorted(pending, key=lambda it: it.get("attempts", 0))

    still_pending = []
    resolved_count = 0
    for item in pending_sorted:
        ticker, side, qty = item["ticker"], item["side"], item["qty"]
        pool = pools.get((ticker, side), [])
        match = next((t for t in pool if abs(t.quantity) == qty), None)

        if match is None:
            item["attempts"] = item.get("attempts", 0) + 1
            still_pending.append(item)
            print(f"  [{ticker}] side={side} qty={qty} "
                  f"-> no matching Flex trade found (attempt {item['attempts']}).")
            continue

        pool.remove(match)  # claimed -- don't let another pending item reuse it
        resolved_count += 1
        print(f"  [{ticker}] side={side} qty={qty} -> MATCHED {match.date_time} "
              f"price={match.trade_price} commission=${match.commission:.4f} "
              f"fifoPnlRealized={match.fifo_pnl_realized:.2f} (real ibOrderID={match.order_id})")

        if dry_run:
            continue

        if side == "entry" and ticker in positions.get("positions", {}):
            pos = positions["positions"][ticker]
            pos["cost_basis"] = pos.get("cost_basis", 0.0) + abs(match.commission)
            pos["entry_commission"] = pos.get("entry_commission", 0.0) + abs(match.commission)
        else:
            equity["cash"] = equity.get("cash", 0.0) - abs(match.commission)
            append_trade(state_dir, datetime.now(timezone.utc), ticker, "LONG", 0.0, 0.0, qty,
                         -abs(match.commission), 0.0, "commission_correction",
                         note=f"Flex-resolved {side} commission, matched {match.date_time} "
                              f"real ibOrderID={match.order_id}",
                         commission=abs(match.commission))

    if not dry_run:
        _save_json(pending_path, {"pending": still_pending})
        _save_json(positions_path, positions)
        equity["updated_at"] = datetime.now(timezone.utc).isoformat()
        _save_json(equity_path, equity)

    print(f"\n{resolved_count}/{len(pending)} resolved, "
          f"{len(still_pending)} still pending."
          f"{' (dry run -- nothing written)' if dry_run else ''}")
