"""Telegram Login Widget + email/password auth and JWT issuance for WebTrader."""
from __future__ import annotations

import hashlib
import hmac
import logging
import re
import time
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext

from ...config import get_settings
from ...database import get_pool
from ...users import _bootstrap_new_user, upsert_user

logger = logging.getLogger(__name__)
from .schemas import (
    EmailLoginRequest,
    EmailRegisterRequest,
    LinkEmailRequest,
    TelegramAuthPayload,
    TokenResponse,
)

_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_MAX_AUTH_AGE = 86400  # 24 hours

_bearer = HTTPBearer(auto_error=False)


def _build_data_check_string(payload: TelegramAuthPayload) -> str:
    fields = payload.model_dump(exclude={"hash"}, exclude_none=True)
    return "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))


def _verify_hash(payload: TelegramAuthPayload, bot_token: str) -> bool:
    check_string = _build_data_check_string(payload)
    secret_key = hashlib.sha256(bot_token.encode()).digest()
    expected = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, payload.hash)


async def authenticate_telegram(data: TelegramAuthPayload) -> TokenResponse:
    settings = get_settings()

    if not _verify_hash(data, settings.TELEGRAM_BOT_TOKEN):
        raise HTTPException(status_code=401, detail="invalid telegram auth hash")

    if time.time() - data.auth_date > _MAX_AUTH_AGE:
        raise HTTPException(status_code=401, detail="auth_date expired")

    if not settings.WEBTRADER_JWT_SECRET:
        raise HTTPException(status_code=503, detail="web dashboard not configured — JWT_SECRET missing")

    # Auto-register via upsert_user — same as /start bot flow.
    # New users: creates users row, user_settings, wallet ($1000 paper),
    # signal_following enrollment, demo feed subscription.
    # Existing users: no-op (idempotent).
    user_row = await upsert_user(data.id, data.username)
    user_db_id = user_row["id"]

    now = int(time.time())
    token_payload = {
        "user_id": str(user_db_id),
        "telegram_id": data.id,
        "first_name": data.first_name,
        "iat": now,
        "exp": now + _MAX_AUTH_AGE,
    }
    token = jwt.encode(token_payload, settings.WEBTRADER_JWT_SECRET, algorithm="HS256")
    return TokenResponse(
        access_token=token,
        user_id=str(user_db_id),
        first_name=data.first_name,
    )


def decode_jwt(raw: str) -> dict:
    settings = get_settings()
    if not settings.WEBTRADER_JWT_SECRET:
        raise HTTPException(status_code=503, detail="web dashboard not configured")
    try:
        return jwt.decode(raw, settings.WEBTRADER_JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="invalid token")


async def get_current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    token: Optional[str] = Query(default=None),
) -> dict:
    raw = (creds.credentials if creds else None) or token
    if not raw:
        raise HTTPException(status_code=401, detail="not authenticated")
    return decode_jwt(raw)


def _issue_token(user_id: str, first_name: str, telegram_id: Optional[int] = None) -> TokenResponse:
    settings = get_settings()
    if not settings.WEBTRADER_JWT_SECRET:
        raise HTTPException(status_code=503, detail="web dashboard not configured — JWT_SECRET missing")
    now = int(time.time())
    payload: dict = {
        "user_id": user_id,
        "first_name": first_name,
        "iat": now,
        "exp": now + _MAX_AUTH_AGE,
    }
    if telegram_id is not None:
        payload["telegram_id"] = telegram_id
    token = jwt.encode(payload, settings.WEBTRADER_JWT_SECRET, algorithm="HS256")
    return TokenResponse(access_token=token, user_id=user_id, first_name=first_name)


async def register_email(data: EmailRegisterRequest) -> TokenResponse:
    """Register a new account with email + password (no Telegram required)."""
    if not _EMAIL_RE.match(data.email):
        raise HTTPException(status_code=422, detail="invalid email address")
    if len(data.password) < 8:
        raise HTTPException(status_code=422, detail="password must be at least 8 characters")
    if len(data.password.encode("utf-8")) > 72:
        raise HTTPException(status_code=422, detail="password must be 72 characters or fewer")
    if not data.first_name.strip():
        raise HTTPException(status_code=422, detail="first_name is required")

    pool = get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT id FROM users WHERE email = $1", data.email.lower()
        )
        if existing:
            raise HTTPException(status_code=409, detail="email already registered")

        pw_hash = _pwd_ctx.hash(data.password)
        row = await conn.fetchrow(
            """INSERT INTO users (email, password_hash, username, role)
               VALUES ($1, $2, $3, 'user')
               RETURNING id""",
            data.email.lower(), pw_hash, data.first_name.strip(),
        )
        user_id = str(row["id"])

        # PAPER-default invariant (F-MEDIUM-1): create user_settings in the
        # same transaction as users INSERT, with trading_mode='paper'
        # written explicitly. Mirrors users.upsert_user for the Telegram
        # path so WebTrader-signup users get the same row at creation time
        # (no lazy create in get_settings_for).
        await conn.execute(
            "INSERT INTO user_settings (user_id, trading_mode) "
            "VALUES ($1, 'paper') ON CONFLICT (user_id) DO NOTHING",
            row["id"],
        )

    # Bootstrap wallet + settings the same way upsert_user does for Telegram.
    # F-LOW-1: log the exception instead of silently swallowing; bootstrap
    # remains best-effort (user row already created), but a failure leaves
    # the new user without a wallet seed and must be observable.
    try:
        await _bootstrap_new_user(row["id"])
    except Exception:  # noqa: BLE001
        logger.exception(
            "webtrader signup: _bootstrap_new_user failed user_id=%s",
            row["id"],
        )

    return _issue_token(user_id, data.first_name.strip())


async def login_email(data: EmailLoginRequest) -> TokenResponse:
    """Authenticate with email + password."""
    if len(data.password.encode("utf-8")) > 72:
        raise HTTPException(status_code=401, detail="invalid email or password")
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, password_hash, username, telegram_user_id FROM users WHERE email = $1",
            data.email.lower(),
        )
    if not row or not row["password_hash"]:
        raise HTTPException(status_code=401, detail="invalid email or password")
    if not _pwd_ctx.verify(data.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="invalid email or password")

    first_name = str(row["username"] or data.email.split("@")[0])
    return _issue_token(
        str(row["id"]), first_name,
        telegram_id=row["telegram_user_id"],
    )


async def link_email(user_id: str, data: LinkEmailRequest) -> dict:
    """Add email + password to an existing Telegram account (from Settings)."""
    if not _EMAIL_RE.match(data.email):
        raise HTTPException(status_code=422, detail="invalid email address")
    if len(data.password) < 8:
        raise HTTPException(status_code=422, detail="password must be at least 8 characters")
    if len(data.password.encode("utf-8")) > 72:
        raise HTTPException(status_code=422, detail="password must be 72 characters or fewer")

    pool = get_pool()
    async with pool.acquire() as conn:
        conflict = await conn.fetchrow(
            "SELECT id FROM users WHERE email = $1 AND id != $2::uuid",
            data.email.lower(), user_id,
        )
        if conflict:
            raise HTTPException(status_code=409, detail="email already in use")

        existing = await conn.fetchrow(
            "SELECT email FROM users WHERE id = $1::uuid", user_id
        )
        if existing and existing["email"]:
            raise HTTPException(status_code=409, detail="account already has an email linked")

        pw_hash = _pwd_ctx.hash(data.password)
        await conn.execute(
            "UPDATE users SET email = $1, password_hash = $2 WHERE id = $3::uuid",
            data.email.lower(), pw_hash, user_id,
        )
    return {"ok": True}
