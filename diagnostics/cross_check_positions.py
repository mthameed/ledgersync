"""Cross-checks a local position record against IBKR's actual broker-side
holdings, symbol by symbol.

Connects to a running TWS/IB Gateway instance (paper or live) and compares
what it reports as open positions against a local positions.json. Any
difference is a signal that local state has drifted from the real account
-- worth running periodically, and definitely worth running right after any
incident (reboot, crash, dropped connection) you suspect might have caused
a desync.

Scope note: this checks ONE account against ONE local state file. If you
run several accounts (e.g. one per strategy or Gateway instance), run this
once per account with that account's own --port/--client-id/--account and
diff it against that account's own state file -- that is the cleanly
attributable case. Summing positions across several local books that share
one broker account is a materially different (and much weaker) check and
isn't attempted here; keep accounts separate if you want this check to be
unambiguous.

Read-only -- connects with its own, separate client id, so it never
collides with a running trading process on the same account.

Usage:
    python -m diagnostics.cross_check_positions --port 7497 --client-id 99 \\
        --positions-file state/positions.json [--account YOUR_ACCOUNT_ID]

Requires ib_insync (pip install ib_insync). This is the only part of
LedgerSync that needs a live TWS/Gateway connection rather than just the
Flex Query report, so it's kept as an optional diagnostic rather than a
core dependency.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path


def _load_positions(path: Path) -> dict[str, int]:
    if not path.exists():
        return {}
    with open(path) as f:
        data = json.load(f)
    return {ticker: pos["qty"] for ticker, pos in data.get("positions", {}).items()}


async def _broker_positions(host: str, port: int, client_id: int, account: str | None) -> dict[str, int]:
    try:
        from ib_insync import IB
    except ImportError as e:
        raise RuntimeError(
            "This diagnostic needs ib_insync: pip install ib_insync") from e

    ib = IB()
    await ib.connectAsync(host, port, clientId=client_id, timeout=10)
    try:
        await ib.reqPositionsAsync()
        out: dict[str, int] = {}
        for p in ib.positions():
            if account is not None and p.account != account:
                continue
            out[p.contract.symbol] = out.get(p.contract.symbol, 0) + int(p.position)
        return out
    finally:
        ib.disconnect()


async def check(host: str, port: int, client_id: int, account: str | None,
                 positions_file: Path) -> bool:
    local = _load_positions(positions_file)
    broker = await _broker_positions(host, port, client_id, account)

    label = account or f"port {port}"
    print(f"\n=== {label} ===")
    print(f"{'Symbol':<8} {'Broker':>8} {'Local':>8} {'Match':>10}")
    print("-" * 38)
    ok = True
    for sym in sorted(set(broker) | set(local)):
        b, l = broker.get(sym, 0), local.get(sym, 0)
        match = "OK" if b == l else "MISMATCH"
        if b != l:
            ok = False
        print(f"{sym:<8} {b:>8} {l:>8} {match:>10}")
    if not broker and not local:
        print("(flat -- no positions on either side)")
    return ok


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, required=True,
                     help="7497=TWS paper, 7496=TWS live, 4002=Gateway paper, 4001=Gateway live")
    ap.add_argument("--client-id", type=int, default=99)
    ap.add_argument("--account", default=None,
                     help="Filter to one account id, if this Gateway session serves more than one")
    ap.add_argument("--positions-file", type=Path, required=True)
    args = ap.parse_args()

    try:
        ok = asyncio.run(check(args.host, args.port, args.client_id, args.account, args.positions_file))
    except Exception as e:
        print(f"FAIL: {e}")
        sys.exit(1)

    print()
    if ok:
        print("All symbols reconcile.")
    else:
        print("MISMATCH(ES) FOUND -- local position record disagrees with the broker. "
              "Investigate before trusting any affected P&L.")
        sys.exit(1)


if __name__ == "__main__":
    main()
