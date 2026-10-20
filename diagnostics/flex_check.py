"""Validates a Flex Query's setup before it's relied on.

Run this against a new token/query as soon as you create it. It checks the
thing that actually breaks: whether the query returns Trade rows carrying
every attribute ledgersync.flex_query._parse_trades() reads. A query
created with the right type and period but the wrong fields ticked looks
fine in the IBKR portal and fails only later, mid-reconciliation, as a
TypeError on float(None).

Usage:
    python -m diagnostics.flex_check --token YOUR_TOKEN --query-id YOUR_QUERY_ID

Exit 0 = usable, 1 = something is wrong (message says what).
"""
from __future__ import annotations

import argparse
import re
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter

import requests

from ledgersync.flex_query import SEND_HOST, SEND_URL

# Exactly what _parse_trades() pulls off each <Trade> element. A query
# missing any of these is unusable no matter how healthy it looks in the
# portal.
REQUIRED_FIELDS = [
    "symbol", "dateTime", "quantity", "tradePrice",
    "ibCommission", "fifoPnlRealized", "buySell", "ibOrderID", "ibExecID",
]


def fetch_raw(token: str, query_id: str, max_wait_s: float = 60.0) -> str:
    send = requests.get(SEND_URL, params={"t": token, "q": query_id, "v": "3"}, timeout=30)
    send.raise_for_status()
    if "<ErrorCode>" in send.text:
        code = re.search(r"<ErrorCode>(\d+)</ErrorCode>", send.text)
        msg = re.search(r"<ErrorMessage>(.*?)</ErrorMessage>", send.text)
        raise RuntimeError(f"SendRequest rejected (code {code.group(1) if code else '?'}): "
                           f"{msg.group(1) if msg else send.text}")
    ref = re.search(r"<ReferenceCode>(\d+)</ReferenceCode>", send.text)
    url = re.search(r"<Url>(.*?)</Url>", send.text)
    if not ref or not url:
        raise RuntimeError(f"SendRequest gave no ReferenceCode/Url: {send.text}")
    # Same regional-host substitution as flex_query.py -- see its comment.
    get_url = re.sub(r"https://[^/]+", f"https://{SEND_HOST}", url.group(1))

    elapsed = 0.0
    while elapsed < max_wait_s:
        time.sleep(3.0)
        elapsed += 3.0
        resp = requests.get(get_url, params={"q": ref.group(1), "t": token, "v": "3"}, timeout=30)
        if "<FlexQueryResponse" in resp.text:
            return resp.text
    raise RuntimeError(f"No report within {max_wait_s}s")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--token", required=True, help="Flex Web Service token for the account")
    ap.add_argument("--query-id", required=True, help="Flex Query id to validate")
    args = ap.parse_args()

    print(f"Requesting Flex report for query {args.query_id} (10-30s) ...")
    try:
        xml_text = fetch_raw(args.token, args.query_id)
    except Exception as e:
        print(f"FAIL: {e}")
        sys.exit(1)

    root = ET.fromstring(xml_text)
    trades = list(root.iter("Trade"))
    accts = {el.get("accountId") for el in trades if el.get("accountId")}

    print(f"Report OK -- {len(trades)} Trade row(s).")
    if accts:
        print(f"Account(s) covered: {', '.join(sorted(accts))}")

    if not trades:
        print("\nWARN: no Trade rows. Expected for a brand-new account with no fills yet -- "
              "the query itself works. Re-run after this account has traded to confirm the "
              "field selection.")
        sys.exit(0)

    missing = [f for f in REQUIRED_FIELDS if trades[0].get(f) is None]
    if missing:
        print(f"\nFAIL: Trade rows are missing required field(s): {', '.join(missing)}")
        print("Edit the query and tick these in the Trades section, then re-run.")
        sys.exit(1)

    print(f"All {len(REQUIRED_FIELDS)} required fields present.")
    dates = sorted(t.get("dateTime", "")[:8] for t in trades)
    print(f"Date range covered: {dates[0]} .. {dates[-1]}")

    # Execution-level detail matters: a single order can fill in several
    # parts, and the reconciliation logic aggregates those by ibOrderID.
    # levelOfDetail is usually NOT among the selected fields, so infer from
    # the data instead: repeated ibOrderID with distinct ibExecID is proof
    # of execution-level rows. Absence of repeats is NOT evidence of a
    # problem -- it just means no order happened to split.
    per_order = Counter(t.get("ibOrderID") for t in trades)
    split_orders = sum(1 for n in per_order.values() if n > 1)
    print(f"Orders: {len(per_order)} distinct; {split_orders} arrived as multiple fills"
          f"{' (confirms execution-level rows)' if split_orders else ''}")
    print("\nUsable.")


if __name__ == "__main__":
    main()
