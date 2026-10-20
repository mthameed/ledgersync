"""Command-line entry point for LedgerSync.

    ledgersync resolve-commissions --config config.json
    ledgersync resolve-closes --config config.json --dry-run
    ledgersync resolve-all --state-dir ./state

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
        description="Reconciles local trade/position/equity state against IBKR's Flex Query reporting data.")
    parser.add_argument("--config", type=Path, default=None,
                         help="Path to a JSON config file (see config.example.json). "
                              "Environment variables IBKR_ACCOUNT_ID / IBKR_FLEX_TOKEN / "
                              "IBKR_FLEX_QUERY_ID take precedence over anything in this file.")
    parser.add_argument("--state-dir", type=Path, default=None,
                         help="Directory holding this account's state JSON/CSV files "
                              "(default: ./state, or the config file's state_dir).")
    parser.add_argument("--dry-run", action="store_true",
                         help="Print what would be resolved without writing any state.")

    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("resolve-commissions",
                    help="Resolve the pending-commissions queue against Flex Query data.")
    sub.add_parser("resolve-closes",
                    help="Resolve the pending-closes queue against Flex Query data.")
    sub.add_parser("resolve-all",
                    help="Run resolve-commissions, then resolve-closes.")

    args = parser.parse_args()
    cfg = load_config(args.config, state_dir=args.state_dir)

    if args.command in ("resolve-commissions", "resolve-all"):
        resolve_pending_commissions.resolve(
            cfg.state_dir, cfg.flex_token, cfg.flex_query_id, dry_run=args.dry_run)
    if args.command in ("resolve-closes", "resolve-all"):
        resolve_pending_closes.resolve(
            cfg.state_dir, cfg.flex_token, cfg.flex_query_id, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
