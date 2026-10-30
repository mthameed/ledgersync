# Changelog

## 0.1.0 — 2026-10-30

Initial release of LedgerSync (Free).

- Previews reconciliation of pending commissions and pending closes against
  real IBKR Flex Query data: matches, split-fill aggregation, newest-first
  duplicate-candidate disambiguation, all printed.
- `diagnostics.flex_check` validates a Flex token/query before relying on it.
- No write-back capability -- this package only ever previews. See
  LedgerSync (Pro) for applying corrections and the optional live-position
  cross-check.
