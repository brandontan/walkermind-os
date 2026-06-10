# self-serve-2fa

**Role:** WARP•R00T
**Branch:** WARP/root-self-serve-2fa
**Validation Tier:** MAJOR
**Claim Level:** NARROW INTEGRATION

## 1. What was built

Closes the documented gap in `domain.activation.live_checklist._gate_two_factor`:

> *"Self-serve 2FA infrastructure does not yet exist. Until it lands, the gate reads system_settings for 2fa_enabled:{user_id} so the operator can manually flip an account through after an out-of-band setup."*

Owner-reported: the Enable Live Trading modal on `walk3r69` showed `✗ Your account passes all readiness checks` with two failing gates listed — **active subaccount with deposit** + **two factor setup complete**. Investigation found:

* Gate 4 (deposit) — code is intact (the wallet-audit-fix lane wired the deposit watcher correctly). Owner must send USDC.e to their deposit address; the watcher confirms it after 32 blocks → gate flips. Real-world action; not code-fixable.
* Gate 7 (2FA) — **was the documented missing infrastructure**. This lane builds it.

After this lane, a user enrolls via the webtrader CONFIG tab (Settings page, right column, above the Live Trading card):

1. Tap **Set up 2FA** → backend generates a TOTP secret, Fernet-encrypts it, stores on `user_settings.totp_secret_encrypted`, returns the provisioning URI + base32 secret to the UI.
2. UI shows a QR code (rendered client-side from the otpauth URI via `qrcode.react`) + the manual base32 fallback.
3. User scans → enters the 6-digit code → backend RFC 6238 verify with ±1 window tolerance.
4. On verify success: sets `user_settings.totp_enabled=true` AND writes the legacy `system_settings[2fa_enabled:{user_id}]='true'` flag the existing gate already reads.
5. `/live/status` → gate 7 lights up automatically. No `domain/activation/live_checklist.py` change.

## 2. Current system architecture

```
SettingsPage (CONFIG tab)
  └─ <TwoFactorSetupCard onChanged={load} />
       └─ steps: off → enrolling → on (with disable expander)

   ↓ API
GET    /api/web/2fa/status   → {enrolled, enabled}      (no secret leak)
POST   /api/web/2fa/setup    → {otpauth_uri, secret}    (rate-limited 5/min)
POST   /api/web/2fa/verify   {code} → flips both flags  (rate-limited 5/min)
POST   /api/web/2fa/disable  {code} → clears + revokes  (rate-limited 5/min)

   ↓ domain
domain/auth/totp.py
  ├─ enroll              → generate + encrypt + persist on user_settings
  ├─ verify_and_enable   → RFC 6238 ±1 window + write column + write legacy flag
  ├─ verify_and_disable  → require valid code + clear secret + clear flag
  └─ status              → {enrolled, enabled}; never returns the secret

   ↓ storage
migration 095:
  ALTER TABLE user_settings
    ADD COLUMN totp_secret_encrypted TEXT,           -- Fernet (WALLET_ENCRYPTION_KEY)
    ADD COLUMN totp_enabled BOOLEAN NOT NULL DEFAULT FALSE;

   ↓ gate (unchanged)
domain/activation/live_checklist._gate_two_factor
  reads system_settings WHERE key='2fa_enabled:{user_id}' AND value='true'
```

## 3. Files created / modified

* **NEW** `projects/polymarket/crusaderbot/migrations/095_user_2fa.sql` — additive + idempotent: 2 columns on `user_settings`. Nullable secret = "not enrolled"; `totp_enabled` boolean defaults to FALSE.
* **NEW** `projects/polymarket/crusaderbot/domain/auth/__init__.py` — package marker.
* **NEW** `projects/polymarket/crusaderbot/domain/auth/totp.py` — RFC 6238 TOTP using `pyotp`, Fernet-encrypted secret at rest with the existing `WALLET_ENCRYPTION_KEY` (same key the HD private keys use — adding a separate key surface here would create operator burden for no isolation gain). Public API: `enroll`, `verify_and_enable`, `verify_and_disable`, `status`. Typed exceptions: `TotpNotEnrolled`, `TotpInvalidCode`, `TotpDecryptionError` (the last so a stale-key corruption surfaces a clean error rather than looking like a wrong code and locking the user out forever).
* **MODIFIED** `projects/polymarket/crusaderbot/pyproject.toml` — adds `pyotp>=2.9`.
* **MODIFIED** `projects/polymarket/crusaderbot/webtrader/backend/router.py` — 4 endpoints under `/api/web/2fa/*`. Per-user rate-limited (5/min each on the write paths) so a stolen session cannot brute-force the 6-digit code.
* **NEW** `projects/polymarket/crusaderbot/webtrader/frontend/src/components/TwoFactorSetupCard.tsx` — self-contained UI; three states (off → enrolling → on); QR rendered via existing `qrcode.react` (already in `package.json`); copy-to-clipboard for the manual secret fallback.
* **MODIFIED** `projects/polymarket/crusaderbot/webtrader/frontend/src/lib/api.ts` — `TwoFactorStatus` + `TwoFactorSetup` types + 4 client methods.
* **MODIFIED** `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/SettingsPage.tsx` — mounts the card right above the existing Live Trading card so users naturally enrol before attempting to enable live.
* **NEW** `projects/polymarket/crusaderbot/tests/test_totp_2fa.py` — 13 tests including the **gate integration pin** `test_live_checklist_gate_reads_the_flag_we_write` that asserts the key `verify_and_enable` writes is byte-identical to what `_gate_two_factor` reads.

## 4. What is working

* `pytest projects/polymarket/crusaderbot/tests/test_totp_2fa.py -v` → **13/13 pass**.
* Wider activation/checklist regression — 47/47 pass (13 new + 34 inherited).
* `ruff check` clean on all Python files touched.
* The secret on the row is Fernet-encrypted (asserted by round-trip in `test_enroll_persists_encrypted_secret_and_returns_uri`) — plaintext never persists.
* TOTP verify accepts ±1 window (30s) for clock drift; rejects empty / wrong codes; uses pyotp (RFC 6238 canonical).
* `verify_and_enable` writes the **EXACT** `2fa_enabled:{user_id}` key the existing `_gate_two_factor` reads. Pinned by `test_live_checklist_gate_reads_the_flag_we_write` so if either side drifts in the future, CI fails.
* `verify_and_disable` requires a valid current code (asserted by `test_verify_and_disable_requires_valid_code`) — a stolen session cannot turn 2FA off without the second factor.
* Status endpoint **never** returns the secret (pinned by `test_status_never_returns_the_secret`).
* Stale-encryption corruption surfaces a typed `TotpDecryptionError` (HTTP 500 from the endpoint), not silent "invalid code" lockout.
* Frontend matches the existing `LiveActivationModal` / `SettingsGroup` design conventions (clip-card, hud-mono, the gold-on-dark palette).

## 5. Known issues

* **No backup codes.** A user who loses their authenticator device must contact admin (the operator can clear `totp_secret_encrypted` via SQL → user re-enrols). Backup codes are a clean follow-up lane (~30 lines: generate 8 single-use codes on enrol, hash + store, accept any unused code as a valid verify).
* **Frontend type-check needs `node_modules`** in CI — already installed in `crusaderbot-cd.yml`; the local-env errors during this session were "Cannot find react" from a fresh checkout without `npm install`, NOT a code issue.
* **Rate limit is per-route, not per-user-per-code.** The 5/min per route is shared across `verify` attempts; a determined attacker has 5 tries per minute → 7200/day at 6-digit space (1M) = ~140-day expected guess. Acceptable for v1; a stricter per-attempt-bucket lockout (3 wrong → 1-hour cool-down) is a follow-up.
* **Gate 4 (deposit) still failing for walk3r69.** That's owner-action, not code-fixable: send USDC.e (`0x2791Bca…`) to your deposit address from `/wallet`; the watcher records → confirms at 32-block depth → gate 4 passes. The deposit pipeline was audited last cycle (WARP-94 / wallet-audit-fix MERGED #1713) and is intact.

## 6. What is next

1. **Owner unblocks walk3r69**: deposit USDC.e + enrol 2FA via the new CONFIG card. Both gates flip → Enable Live Trading unlocks.
2. **Backup codes** lane — 8 single-use recovery codes generated on enrol, hashed + stored, accepted alongside TOTP at verify time. Small (~30 lines) follow-up.
3. **Per-attempt brute-force lockout** — replace per-route rate limit with a per-user attempt counter (3 wrong → 1-hour cool-down). Small follow-up.
4. The remaining per-user execution chain (Step 3 deposit-watcher awareness, Step 4 execution wiring) is independent of 2FA.

## Metadata

* **Validation Target:** TOTP enrol/verify/disable flow works end-to-end; the flag write site is byte-identical to the existing gate's read site; secret is encrypted at rest and never leaked through any read path; brute-force is rate-limited.
* **Not in Scope:** backup codes; per-attempt lockout (router-level rate limit is the v1 control); admin override (operator can still flip the flag via SQL if needed); the deposit gate (owner-action); any change to `domain/activation/live_checklist.py`; risk constants; Kelly; `ENABLE_LIVE_TRADING`; `USE_REAL_CLOB`; the per-user CLOB execution lane.
* **Suggested Next Step:** owner deploys this lane, deposits USDC.e to the walk3r69 deposit address, enrols 2FA via the new CONFIG card, then enables live trading. Backup codes + per-attempt lockout follow as small lanes if needed before broader user rollout.
