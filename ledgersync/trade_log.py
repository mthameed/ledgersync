"""Appends one closed/corrected trade row to this account's trades ledger CSV."""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

FIELDS = ["timestamp", "symbol", "direction", "entry_price", "exit_price",
          "qty", "pnl", "r_multiple", "exit_reason", "note", "commission"]


def append_trade(state_dir: Path, timestamp: datetime, symbol: str, direction: str,
                  entry_price: float, exit_price: float, qty: float, pnl: float,
                  r_multiple: float, exit_reason: str, note: str = "",
                  commission: float = 0.0) -> None:
    """Appends one row to <state_dir>/trades.csv, creating it (with a
    header) on first use. `pnl` is expected to already be net of commission
    wherever the caller knows it -- `commission` here is purely for
    reporting/breakdown, not something added into `pnl` again."""
    path = Path(state_dir) / "trades.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists()
    with open(path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if is_new:
            writer.writeheader()
        writer.writerow({
            "timestamp": timestamp.isoformat() if isinstance(timestamp, datetime) else timestamp,
            "symbol": symbol,
            "direction": direction,
            "entry_price": round(entry_price, 4),
            "exit_price": round(exit_price, 4),
            "qty": qty,
            "pnl": round(pnl, 2),
            "r_multiple": round(r_multiple, 3),
            "exit_reason": exit_reason,
            "note": note,
            "commission": round(commission, 2),
        })
