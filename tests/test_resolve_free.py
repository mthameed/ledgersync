"""Tests for LedgerSync (Free)'s resolvers.

Two things matter here: (1) matching/printing works correctly against real
Flex Query shapes (split fills, newest-first disambiguation), same logic as
LedgerSync (Pro); (2) there is no write-back capability -- not "write-back
disabled", but structurally absent. test_no_dry_run_parameter and
test_state_files_never_touched both guard against that regressing."""
from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ledgersync import resolve_pending_closes, resolve_pending_commissions
from ledgersync.flex_query import FlexTrade


def _trade(symbol, date_time, qty, price, commission, pnl, buy_sell, order_id, exec_id="E1"):
    return FlexTrade(symbol=symbol, date_time=date_time, quantity=qty, trade_price=price,
                      commission=commission, fifo_pnl_realized=pnl, buy_sell=buy_sell,
                      order_id=order_id, exec_id=exec_id)


def test_no_dry_run_parameter():
    """Free's resolve() takes no dry_run param -- there's nothing to gate,
    it always previews. A dry_run parameter appearing here would mean
    someone started re-adding write capability behind a flag, exactly the
    tier-flag design flaw this product line already rejected once
    (see Stop Watchdog's build history)."""
    assert "dry_run" not in inspect.signature(resolve_pending_commissions.resolve).parameters
    assert "dry_run" not in inspect.signature(resolve_pending_closes.resolve).parameters


def test_no_write_helpers_exist():
    """Neither module should import or define anything that writes JSON/CSV
    state -- not trade_log.append_trade, not a local _save_json."""
    import ledgersync.resolve_pending_commissions as rpc
    import ledgersync.resolve_pending_closes as rpcl
    assert not hasattr(rpc, "_save_json")
    assert not hasattr(rpcl, "_save_json")
    assert not hasattr(rpc, "append_trade")
    assert not hasattr(rpcl, "append_trade")


def test_resolve_commissions_matches_and_never_writes(tmp_path, monkeypatch, capsys):
    pending = {"pending": [{"ticker": "NVDA", "side": "entry", "qty": 100, "attempts": 0}]}
    pending_path = tmp_path / "pending_commissions.json"
    pending_path.write_text(json.dumps(pending))
    pending_before = pending_path.read_text()

    fake_trades = [_trade("NVDA", "20261012;213815", 100, 118.23, -1.5, 0.0, "BUY", 555)]
    monkeypatch.setattr(resolve_pending_commissions, "fetch_trades", lambda token, query_id: fake_trades)

    resolve_pending_commissions.resolve(tmp_path, "tok", "qid")

    out = capsys.readouterr().out
    assert "MATCHED" in out
    assert "1/1 would resolve" in out
    assert "PREVIEW ONLY" in out
    # Nothing on disk changed, and nothing new was created.
    assert pending_path.read_text() == pending_before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["pending_commissions.json"]


def test_resolve_closes_aggregates_split_fills_and_never_writes(tmp_path, monkeypatch, capsys):
    pending = {"pending": [{"ticker": "AMD", "qty": 150, "entry_time": "2026-10-01T00:00:00"}]}
    pending_path = tmp_path / "pending_closes.json"
    pending_path.write_text(json.dumps(pending))

    fake_trades = [
        _trade("AMD", "20261012;100000", -100, 200.0, -1.0, 80.0, "SELL", 777, "E1"),
        _trade("AMD", "20261012;100001", -50, 201.0, -0.5, 40.0, "SELL", 777, "E2"),
    ]
    monkeypatch.setattr(resolve_pending_closes, "fetch_trades", lambda token, query_id: fake_trades)

    resolve_pending_closes.resolve(tmp_path, "tok", "qid")

    out = capsys.readouterr().out
    assert "2 fill legs" in out
    assert "fifoPnlRealized=120.00" in out  # 80 + 40, both legs aggregated
    assert "1/1 would resolve" in out
    assert sorted(p.name for p in tmp_path.iterdir()) == ["pending_closes.json"]


def test_resolve_commissions_no_match(tmp_path, monkeypatch, capsys):
    pending = {"pending": [{"ticker": "TSLA", "side": "entry", "qty": 10, "attempts": 0}]}
    (tmp_path / "pending_commissions.json").write_text(json.dumps(pending))
    monkeypatch.setattr(resolve_pending_commissions, "fetch_trades", lambda token, query_id: [])

    resolve_pending_commissions.resolve(tmp_path, "tok", "qid")

    out = capsys.readouterr().out
    assert "no matching Flex trade found" in out
    assert "0/1 would resolve" in out
