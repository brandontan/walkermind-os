"""Telegram Login Widget validation and JWT issuance for the WebTrader dashboard."""
from __future__ import annotations

import hashlib
import hmac
import time
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ...config import get_settings
from ...database import get_pool
from .schemas import TelegramAuthPayload, TokenResponse

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

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM users WHERE telegram_user_id = $1",
            data.id,
        )

    if row is None:
        raise HTTPException(
            status_code=403,
            detail="user not registered — start the Telegram bot first",
        )

    now = int(time.time())
    token_payload = {
        "user_id": str(row["id"]),
        "telegram_id": data.id,
        "first_name": data.first_name,
        "iat": now,
        "exp": now + _MAX_AUTH_AGE,
    }
    token = jwt.encode(token_payload, settings.WEBTRADER_JWT_SECRET, algorithm="HS256")
    return TokenResponse(
        access_token=token,
        user_id=str(row["id"]),
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
