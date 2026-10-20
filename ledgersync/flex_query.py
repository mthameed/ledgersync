"""Flex Web Service client -- pulls durable execution/commission data from
IBKR's Flex Query reporting system.

Why this exists: IBKR's live TWS/Gateway API does not reliably retain
execution and commissionReport data across a client disconnect. A process
that connects briefly, places orders, and disconnects before those orders
actually fill can find that by the time it reconnects, the real fill and
commission data is simply gone from anything the live API can query. Flex
Query is IBKR's own purpose-built after-the-fact reporting system and
reliably retains this data for a real window (a configurable number of
days), independent of any client's connect state.

Point this at an Activity Flex Query configured with a Trades section and a
"Last N Calendar Days" period. A Trade Confirmation-type query is tempting
but its Period field can be locked to "Today" on some accounts, which makes
it useless for reconciling anything beyond the current calendar day.
"""
from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import requests

SEND_HOST = "ndcdyn.interactivebrokers.com"
SEND_URL = f"https://{SEND_HOST}/AccountManagement/FlexWebService/SendRequest"


@dataclass
class FlexTrade:
    symbol: str
    date_time: str            # "yyyyMMdd;HHmmss" in the account's configured report timezone
    quantity: float            # signed: positive = bought, negative = sold
    trade_price: float
    commission: float          # negative = a real cost
    fifo_pnl_realized: float   # IBKR's own authoritative realized P&L for this fill
    buy_sell: str               # "BUY" or "SELL"
    order_id: int
    exec_id: str


def fetch_trades(token: str, query_id: str, max_wait_s: float = 60.0) -> list[FlexTrade]:
    """Runs the full SendRequest -> GetStatement flow and returns every
    Trade row in the report. Report generation is asynchronous on IBKR's
    side, so GetStatement is retried with a short delay until the real
    report (not a "still generating" response) comes back, or max_wait_s
    elapses.

    token/query_id select which account and report to pull -- Flex tokens
    are per-account, so a multi-account setup needs its own token+query pair
    per account. Both are required; there is no default for either."""
    if not token or not query_id:
        raise ValueError("fetch_trades() requires both a Flex token and a Flex query id")

    send = requests.get(SEND_URL, params={"t": token, "q": query_id, "v": "3"}, timeout=30)
    send.raise_for_status()
    ref_match = re.search(r"<ReferenceCode>(\d+)</ReferenceCode>", send.text)
    url_match = re.search(r"<Url>(.*?)</Url>", send.text)
    if not ref_match or not url_match:
        raise RuntimeError(f"Flex SendRequest did not return a ReferenceCode/Url: {send.text}")
    ref_code, get_url = ref_match.group(1), url_match.group(1)
    # IBKR's GetStatement response sometimes points at a regional host that
    # doesn't resolve on every network, even though SEND_HOST does.
    # Substituting SEND_HOST unconditionally (same underlying service) is
    # more reliable than trying the host IBKR gave first and failing.
    get_url = re.sub(r"https://[^/]+", f"https://{SEND_HOST}", get_url)

    elapsed = 0.0
    step = 3.0
    while elapsed < max_wait_s:
        time.sleep(step)
        elapsed += step
        resp = requests.get(get_url, params={"q": ref_code, "t": token, "v": "3"}, timeout=30)
        if "<FlexQueryResponse" in resp.text:
            return _parse_trades(resp.text)
    raise RuntimeError(f"Flex GetStatement did not return a report within {max_wait_s}s")


def _parse_trades(xml_text: str) -> list[FlexTrade]:
    root = ET.fromstring(xml_text)
    trades = []
    for el in root.iter("Trade"):
        trades.append(FlexTrade(
            symbol=el.get("symbol"),
            date_time=el.get("dateTime"),
            quantity=float(el.get("quantity")),
            trade_price=float(el.get("tradePrice")),
            commission=float(el.get("ibCommission")),
            fifo_pnl_realized=float(el.get("fifoPnlRealized")),
            buy_sell=el.get("buySell"),
            order_id=int(el.get("ibOrderID")),
            exec_id=el.get("ibExecID"),
        ))
    return trades
