"""Polymarket Bridge / pUSD settlement services (#1805).

Safe groundwork only: the status poller OBSERVES terminal Bridge COMPLETED
pUSD settlements and routes them to operator manual review with an honest
user notification. It NEVER credits tradeable balance — native USDC/USDT stay
disabled for crediting until the documented precondition chain is met (see
reports/forge/polymarket-bridge-native-enablement-blocker.md).
"""
