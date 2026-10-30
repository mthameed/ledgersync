"""Command-line entry point for LedgerSync (Free).

    ledgersync resolve-commissions --config config.json
    ledgersync resolve-closes --config config.json
    ledgersync resolve-all --config config.json

Preview only: this build matches your pending queue against real Flex Query
data and prints every match, but never writes a correction to your state
files -- that capability doesn't exist in this package. See
LedgerSync (Pro) at https://algovigil.com/ledgersync for the version that
applies corrections, plus the optional live-position cross-check.

Credentials (IBKR_ACCOUNT_ID / IBKR_FLEX_TOKEN / IBKR_FLEX_QUERY_ID) come
from environment variables, or from the --config JSON file -- see
config.example.json and ledgersync/config.py. There is no built-in default
for any of them.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from . import resolve_pending_closes, resolve_pending_commissions
from .config import load_config


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="ledgersync",
        description="LedgerSync (Free) -- previews reconciliation of local trade/position/equity "
                     "state against IBKR's Flex Query reporting data. Matches and prints; "
                     "does not write corrections. See LedgerSync (Pro) to apply them.")
    parser.add_argument("--config", type=Path, default=None,
                         help="Path to a JSON config file (see config.example.json). "
                              "Environment variables IBKR_ACCOUNT_ID / IBKR_FLEX_TOKEN / "
                              "IBKR_FLEX_QUERY_ID take precedence over anything in this file.")
    parser.add_argument("--state-dir", type=Path, default=None,
                         help="Directory holding this account's state JSON/CSV files "
                              "(default: ./state, or the config file's state_dir).")

    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("resolve-commissions",
                    help="Preview matches for the pending-commissions queue against Flex Query data.")
    sub.add_parser("resolve-closes",
                    help="Preview matches for the pending-closes queue against Flex Query data.")
    sub.add_parser("resolve-all",
                    help="Run resolve-commissions, then resolve-closes.")

    args = parser.parse_args()
    cfg = load_config(args.config, state_dir=args.state_dir)

    if args.command in ("resolve-commissions", "resolve-all"):
        resolve_pending_commissions.resolve(cfg.state_dir, cfg.flex_token, cfg.flex_query_id)
    if args.command in ("resolve-closes", "resolve-all"):
        resolve_pending_closes.resolve(cfg.state_dir, cfg.flex_token, cfg.flex_query_id)


if __name__ == "__main__":
    main()
