# WARP-74 Lane 2 — Live-Reconcile Staging Proof Runbook

**Purpose.** Prove the three P0 reconcile gaps (merged in #1613) hold against a
**real Polymarket CLOB broker** — the final gate before `ENABLE_LIVE_TRADING`.
Hermetic tests (`tests/test_live_reconcile.py`) already prove the routing logic;
this proves the one thing fakes cannot: that a broker `cancel_all` actually pulls
a resting GTC off-chain, that real `get_open_orders` truth drives adoption, and
that drift detection sees a real orphan.

**Harness.** `projects/polymarket/crusaderbot/tests/staging/test_live_reconcile_staging.py`

> ⚠️ **Polymarket is Polygon mainnet only — there is no testnet.** This proof uses
> an **isolated throwaway wallet** with **minimal USDC** and **tiny orders**.
> The DB side of every test is an in-memory recording fake — **no database is ever
> written**, only the broker is real.

---

## 0. Hard safety rules (read before anything)

- **NEVER run this against the prod Fly app or prod Supabase.** Run only from a
  **separate staging Fly app** (or a local shell) whose env points at the
  throwaway wallet. Prod must keep `USE_REAL_CLOB=False` so its data collection is
  undisturbed.
- The staging wallet is **throwaway**: fund it with the **minimum** USDC required
  to place a single tiny order (≈ $2 covers every non-fill case with headroom).
- **Fill-dependent sub-cases burn real USDC.** They stay skipped unless you opt in
  with `STAGING_ALLOW_FILLS=1`. Leave them off unless you intend to spend.
- Every test cancels all of its own resting orders on teardown. If a run is
  interrupted, manually confirm the wallet has **zero open orders** on
  polymarket.com before walking away.

---

## 1. Prerequisites

| Item | Detail |
|---|---|
| Isolated wallet | Fresh EOA/Safe, **not** the prod trading wallet. Holds only throwaway USDC. |
| USDC on Polygon | Minimal (≈ $2). Bridged to the wallet / proxy per `web3-polymarket` skill. |
| Staging market | One **liquid** market trading **well above** `STAGING_REST_PRICE` so a BUY at that price rests (never fills). Note its condition id + YES/NO token ids. |
| Python env | Repo deps installed (`pip install -r requirements.txt`); `pytest` + `pytest-asyncio`. |
| Separate app | A staging Fly app or local shell. **Not** prod. |

### Environment variables

| Var | Required | Default | Meaning |
|---|---|---|---|
| `STAGING_WALLET_KEY` | **yes** | — | Throwaway wallet private key. Absent ⇒ whole suite skips. |
| `STAGING_TOKEN_ID` | yes (broker cases) | — | YES outcome token of the staging market. |
| `STAGING_MARKET_ID` | yes (broker cases) | — | Condition id of the staging market. |
| `STAGING_NO_TOKEN_ID` | no | — | NO outcome token (for completeness in the market row). |
| `STAGING_FUNDER_ADDRESS` | depends | — | Proxy/Safe funder address (signature_type 1/2). |
| `STAGING_SIGNATURE_TYPE` | no | `2` | 0=EOA, 1=POLY_PROXY, 2=GNOSIS_SAFE. |
| `STAGING_POLYMARKET_API_KEY` / `_SECRET` / `_PASSPHRASE` | no | — | L2 creds. If unset, auto-derived from the key at runtime. |
| `STAGING_REST_PRICE` | no | `0.10` | BUY price for resting orders — must sit far below market. |
| `STAGING_ORDER_SHARES` | no | `12` | Share count (≈ $1.20 notional at default price; clears the ~$1 min). |
| `STAGING_TICK_SIZE` | no | `0.01` | Market tick size. |
| `STAGING_NEG_RISK` | no | `false` | Set `true` only for neg-risk markets. |
| `STAGING_ALLOW_FILLS` | no | unset | `1` enables fill-burning sub-cases (finalize-once). |
| `STAGING_FILLED_CLOSE_ID` | only for finalize | — | A terminally-FILLED close order id (operator-produced). |

> **Dry run first (no wallet):** `pytest tests/staging/ -q` with **no**
> `STAGING_WALLET_KEY` must report **all skipped, zero failures**. This is the CI
> posture — confirm it before provisioning anything.

---

## 2. Execution

From repo root, with the env above exported in the **staging** shell:

```bash
# Non-fill cases (safe — only places resting orders, cancels them on teardown):
pytest projects/polymarket/crusaderbot/tests/staging/test_live_reconcile_staging.py -v

# To additionally run the fill-burning finalize case (spends real USDC):
STAGING_ALLOW_FILLS=1 STAGING_FILLED_CLOSE_ID=<filled_order_id> \
  pytest projects/polymarket/crusaderbot/tests/staging/test_live_reconcile_staging.py -v
```

Run cases one at a time with `-k` while capturing evidence (§4):
`-k case3`, `-k case2`, `-k case1`, `-k case4`, `-k case5`.

---

## 3. Acceptance cases

For each: **Setup** (what the harness places on the real broker), **Expected**
(the assertion + the operator alert text), **PASS/FAIL**.

### Case 3 — Kill switch broker cancel-all  *(headline proof — run first)*
`-k test_case3`
- **Setup:** harness places one tiny resting GTC BUY; confirms it is on the book.
- **Action:** drives `kill_switch_exec._broker_cancel_all_orders()` against the
  real staging client (its own client, separate from the verifier).
- **Expected:** `broker.get_open_orders(market)` no longer contains the order id.
  In a full `execute_kill_switch` run the operator alert is:
  > 🚨 KILL SWITCH ACTIVATED
  > Reason: …
  > By: …
  (plus `⚠️ BROKER CANCEL FAILED …` **only** if the broker cancel did not engage).
- **PASS:** the resting GTC is **gone** from the exchange. **FAIL:** it is still
  listed, or a `BROKER CANCEL FAILED` warning appears.

### Case 2 — Unknown-order reconcile  `-k test_case2`
Three variants against real `get_open_orders` truth:
- **adopt:** one resting BUY matching the `unknown` row's price+size ⇒ `adopted==1`,
  DB row flipped to `pending` with the broker id. No operator page (audit
  `live_reconcile_adopted`).
- **mismatch:** one resting BUY at a very different price ⇒ `paged==1`, never
  adopted. Alert:
  > ⚠️ LIVE RECONCILE — size/price mismatch
  > … the lone untracked resting order on the token does not match our size/price — NOT adopting. Reconcile manually.
- **halt:** two distinct untracked resting orders ⇒ `halted==1`, kill switch
  engaged. Alert:
  > 🛑 LIVE RECONCILE — UNTRACKED EXPOSURE, TRADING HALTED
  > … N untracked resting orders match; manual reconcile required.
- **PASS:** each variant routes to adopt / page / halt respectively.

### Case 1 — Crash mid-close  `-k test_case1`
- **rollback:** harness places then **cancels** a stand-in close order (terminal,
  zero fills) ⇒ `rolled_back==1`, DB row returned to `open`. No alert.
- **page-no-id:** a `closing` row with no `close_order_id` ⇒ `paged_no_id==1`. Alert:
  > ⚠️ LIVE RECONCILE — stranded close
  > Position … stuck in 'closing' with no close order id. Verify on Polymarket whether the SELL filled, then reconcile.
- **finalize-once** *(fill-gated, `STAGING_ALLOW_FILLS=1` + `STAGING_FILLED_CLOSE_ID`):*
  operator produces a terminally-FILLED close order; reconcile must finalize the
  position **exactly once** and credit proceeds; a second sweep must **not**
  re-credit (`closed==0`). Audit `live_reconcile_closed`.
  - *To produce a filled close:* place a tiny marketable order on the staging
    market (per `web3-polymarket` order patterns), let it fill, pass its id.
  - **page-partial** (terminal KILLED after a partial fill) is the dangerous
    variant — if encountered, the reconciler pages
    `⚠️ LIVE RECONCILE — PARTIAL CLOSE KILLED …` and never auto-finalizes.
- **PASS:** rollback + page-no-id route as above; finalize credits once, second
  sweep is a no-op.

### Case 4 — Broker↔DB drift detector  `-k test_case4`
- **Setup:** harness places one tiny resting order **not** in the (fake) DB, and
  seeds a phantom DB-only id absent from the broker.
- **Expected:** `broker_only>=1` and `db_only>=1`; the real orphan id appears in:
  > ⚠️ ORDER DRIFT DETECTED
  > • N resting order(s) LIVE on the exchange but UNTRACKED in DB (orphan exposure): …
  > • N order(s) marked open in DB but NOT on the exchange …
- **PASS:** both directions surface **and the detector issues zero
  UPDATE/INSERT/DELETE** (alert-only). **FAIL:** any DB mutation, or a direction
  is missed.

### Case 5 — Infra-degraded → paper fallback  `-k test_case5`
- **Setup:** a CLOB dependency failure is injected pre-submit (no wallet needed).
- **Expected:** `router.execute` returns `mode == "paper"` and emits:
  > 🚨 LIVE INFRA DEGRADED — fell back to PAPER
  > market=…
  > A live trade could not reach the exchange (CLOB dependency failure) and was routed to paper.
  > reason: …
- **PASS:** trade routed to paper **and** the alert fired. **FAIL:** the live
  order is duplicated to paper after submit, or no alert.

---

## 4. Evidence capture (attach to the forge/sentinel report)

For each case, capture and file under the WARP-74 report:
1. **Pytest output** — the per-case PASS line (`-v`).
2. **Fly/staging logs** — the structlog events emitted: `kill_switch_exec`,
   `live_reconcile_adopted` / `live_reconcile_close_rolled_back` /
   `live_reconcile_closed`, `order_drift_detected`,
   `live_infra_degraded_paper_fallback`.
3. **Telegram alert screenshot** — the exact operator message per case (§3).
4. **polymarket.com confirmation** — for Case 3, a before/after of the wallet's
   open-orders list showing the resting GTC is gone.

A case is **proven** only when all four artifacts agree with §3. File the bundle,
then return to WARP🔹CMD for the `ENABLE_LIVE_TRADING` go/no-go decision.

---

## 5. Teardown

- Confirm the staging wallet shows **zero open orders** on polymarket.com.
- If `STAGING_ALLOW_FILLS=1` was used, redeem/close any residual position so the
  wallet returns to a clean state.
- Unset the `STAGING_*` env vars from the shell. Never persist `STAGING_WALLET_KEY`.

## 6. Geoblock — running the order-placing cases (1–4)

Polymarket enforces a **server-side regional geoblock** on order placement.
GitHub-**hosted** runners (`ubuntu-latest`) sit in a blocked region, so cases
1–4 return `403 "Trading restricted in your region"` there. Everything else in
the pipeline (auth, signing) works on a hosted runner — only the final `/order`
POST is refused by IP. **case5 places no real orders and runs anywhere** and is
already green on hosted Actions.

The cases that place orders need an **allowed-region egress**. The two ways:

### (Recommended) Run on Fly.io Singapore — zero operator setup

The production app already runs in Fly region **`sin` (Singapore)**, which is
Polymarket-allowed, and the production image already contains the test harness
and all dependencies. A dispatch can use the existing **`FLY_API_TOKEN`** secret to
launch a **one-off Fly machine in `sin`** that runs the harness and exits; the
GitHub-hosted runner only drives `flyctl` (control-plane — not geoblocked).
Nothing to install or keep running locally — you just tap **Run workflow**.

Wired as **`.github/workflows/staging-proof-fly.yml`** ("WARP-74 Staging Proof
(Fly Singapore — order-placing cases)"). It reuses the existing `FLY_API_TOKEN`
and `STAGING_*` secrets, and runs in a DEDICATED isolated app
(`crusaderbot-staging-proof`, no prod secrets) so the proof can never touch the
real wallet. The machine clones the public repo, installs deps exactly like the
hosted runner, and runs pytest from Singapore. Pass/fail is decided by an
explicit `PROOF_RESULT` sentinel in the machine logs (an inconclusive run fails
closed). Dispatch: Actions → that workflow → pick `case` + `signature_type:1`
(proxy) → Run.

### (Alternative) Self-hosted runner on an always-on allowed-region host

Register a self-hosted GitHub runner on any always-on machine in an allowed
region (a small VPS / a Fly machine — **not** required to be your laptop), then
dispatch with input **`runner: self-hosted`**. The `self-hosted` label is
applied automatically. Requirements on the host: Python 3.11, `bash`, outbound
network to Polymarket. For a Magic-link/proxy wallet use `signature_type: 1`
(POLY_PROXY) plus the `STAGING_FUNDER_ADDRESS` (proxy address) secret.
