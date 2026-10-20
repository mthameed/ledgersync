"""Generic configuration loader for LedgerSync.

Loads IBKR Flex Web Service credentials (and the account id they belong to)
either from environment variables, or from a local JSON config file. There
is NO hardcoded fallback value for any of these -- a missing credential
raises a clear RuntimeError rather than silently using a placeholder. A
"default" that merely looks like a plausible token is exactly the kind of
thing that goes unnoticed until it reconciles against the wrong account (or
fails in a confusing way), so this module simply refuses to have one.

Precedence: environment variable, then the JSON config file (if given),
then nothing -- never a built-in default.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

ENV_ACCOUNT_ID = "IBKR_ACCOUNT_ID"
ENV_FLEX_TOKEN = "IBKR_FLEX_TOKEN"
ENV_FLEX_QUERY_ID = "IBKR_FLEX_QUERY_ID"

# env var name -> key used in the JSON config file
_REQUIRED_KEYS = {
    ENV_ACCOUNT_ID: "account_id",
    ENV_FLEX_TOKEN: "flex_token",
    ENV_FLEX_QUERY_ID: "flex_query_id",
}


@dataclass(frozen=True)
class Config:
    account_id: str
    flex_token: str
    flex_query_id: str
    state_dir: Path


def _load_file(config_path: Path | None) -> dict:
    if config_path is None or not config_path.exists():
        return {}
    with open(config_path) as f:
        return json.load(f)


def load_config(config_path: str | Path | None = None,
                 state_dir: str | Path | None = None) -> Config:
    """Resolves credentials from environment variables first, falling back
    to a JSON config file (see config.example.json for the shape) when one
    is given and has that key. Raises RuntimeError naming exactly which
    value(s) are missing -- it never substitutes a default for you.

    config_path: path to a JSON file shaped like config.example.json.
        Optional -- environment variables alone are enough.
    state_dir: directory holding this account's state JSON/CSV files.
        Falls back to the config file's "state_dir" key, then "./state".
    """
    path = Path(config_path) if config_path else None
    file_data = _load_file(path)

    values: dict[str, str | None] = {}
    missing: list[str] = []
    for env_var, file_key in _REQUIRED_KEYS.items():
        val = os.environ.get(env_var) or file_data.get(file_key)
        if not val:
            missing.append(f'{env_var} (env var) / "{file_key}" (config file key)')
        values[file_key] = val

    if missing:
        raise RuntimeError(
            "LedgerSync is missing required configuration:\n  - " +
            "\n  - ".join(missing) +
            "\n\nSet the environment variable(s), or point --config at a JSON file "
            "shaped like config.example.json. There is no default value for any of "
            "these -- they must be configured explicitly before LedgerSync can talk "
            "to IBKR's Flex Web Service."
        )

    resolved_state_dir = Path(state_dir) if state_dir else Path(file_data.get("state_dir", "state"))

    return Config(
        account_id=values["account_id"],
        flex_token=values["flex_token"],
        flex_query_id=values["flex_query_id"],
        state_dir=resolved_state_dir,
    )
