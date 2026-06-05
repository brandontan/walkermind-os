"""WARP-74 Lane 2 — live-broker staging proof harness package.

Every module here is guarded by ``STAGING_WALLET_KEY`` and is a NO-OP in CI:
without an isolated staging wallet provisioned the tests skip cleanly, never
touching the network, the broker, or any database. See
``docs/runbooks/warp74-staging-proof.md`` for the operator procedure.
"""
