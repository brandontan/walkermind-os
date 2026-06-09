# WARP•FORGE Report — auth-password-byte-limit

**Branch:** WARP/auth-password-byte-limit
**Validation Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION
**Validation Target:** WebTrader email auth — register, login, link-email endpoints
**Not in Scope:** Telegram auth, JWT, trading logic, DB migrations
**Suggested Next Step:** WARP🔹CMD review → merge → Fly.io redeploy

---

## 1. What Was Built

Guard against bcrypt's 72-byte password limit in all three email-auth functions.
Passlib raises `ValueError: password cannot be longer than 72 bytes` when a password
submitted to `_pwd_ctx.hash()` or `_pwd_ctx.verify()` exceeds that byte length.
This caused a production 500 at `POST /api/web/auth/register` (Sentry DAWN-SNOWFLAKE-1729-26,
2026-05-25T07:15:26 UTC, iOS Safari user).

Three validation guards added — all checked **before** any bcrypt call:

| Function | Check | Response |
|---|---|---|
| `register_email` | `len(pw.encode("utf-8")) > 72` | 422 — password must be 72 characters or fewer |
| `login_email` | `len(pw.encode("utf-8")) > 72` | 401 — invalid email or password (no info leak) |
| `link_email` | `len(pw.encode("utf-8")) > 72` | 422 — password must be 72 characters or fewer |

Byte-length check (not character count) because bcrypt's limit is in bytes; multi-byte
UTF-8 characters (emoji, CJK) consume more than one byte per character.

Login returns 401 (not 422) intentionally — consistent with the "invalid email or password"
message and avoids leaking that a user with that email exists.

---

## 2. Current System Architecture

Auth module: `crusaderbot/webtrader/backend/auth.py`
Password hashing: `passlib.CryptContext(schemes=["bcrypt"])` — standard bcrypt, 72-byte limit is a bcrypt invariant.
All email-auth paths (register / login / link) flow through this single file.
No change to JWT issuance, Telegram auth, or risk/trading layers.

---

## 3. Files Created / Modified

| Action | Path |
|---|---|
| Modified | `projects/polymarket/crusaderbot/webtrader/backend/auth.py` |

Lines changed: +6 (3 guard blocks, 2 lines each).

---

## 4. What Is Working

- `register_email` returns 422 before reaching `_pwd_ctx.hash()` when password > 72 bytes
- `login_email` returns 401 before reaching `_pwd_ctx.verify()` when password > 72 bytes
- `link_email` returns 422 before reaching `_pwd_ctx.hash()` when password > 72 bytes
- All existing validations (min 8 chars, email regex, first_name required) unchanged
- No DB, migration, or frontend change required

---

## 5. Known Issues

None. This is a pure input-validation guard with no side effects.

---

## 6. What Is Next

- WARP🔹CMD review and merge
- Fly.io redeploy to apply to production
- Resolve Sentry issue DAWN-SNOWFLAKE-1729-26 after deploy
