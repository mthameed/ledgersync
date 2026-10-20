"""Persistence for positions that have been detected as closed broker-side
but whose realized P&L couldn't be determined via the live API within its
retention window -- the same "execution history doesn't reach back far
enough" limitation documented in flex_query.py's docstring.

Rather than discarding this information (losing the trade record and the
ledger credit entirely, which is what naively deleting a "disappeared"
position does), queue it here and resolve it later against Flex Query data
with resolve_pending_closes.py.
"""
from __future__ import annotations

import json
from pathlib import Path


def _path(state_dir: Path) -> Path:
    return Path(state_dir) / "pending_closes.json"


def record_pending_close(state_dir: Path, ticker: str, stale_pos: dict) -> None:
    """stale_pos is whatever your own position record for `ticker` looked
    like right before you discovered it was actually closed broker-side.
    Only the fields below are read; anything else on it is ignored."""
    path = _path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(path.read_text()) if path.exists() else {"pending": []}
    data["pending"].append({
        "ticker": ticker,
        "qty": stale_pos.get("qty"),
        "entry_price": stale_pos.get("entry_price"),
        "r_dist": stale_pos.get("r_dist"),
        # cost_basis is optional: None for ledgers that track running
        # equity/P&L directly rather than a per-position cost basis.
        "cost_basis": stale_pos.get("cost_basis"),
        "entry_time": str(stale_pos.get("entry_time") or stale_pos.get("entry_date") or ""),
        "attempts": 0,
    })
    path.write_text(json.dumps(data, indent=2))
