"""Authentication module for OAuth 2.0 and JWT session tokens.

Provides token generation, Google ID token verification, and FastAPI dependency
``get_current_user`` with automatic fallback to single-user 'local' mode when
unauthenticated.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any

import httpx
from fastapi import Request
from jose import jwt, JWTError

from ..config import settings
from ..db import upsert_user, get_user

logger = logging.getLogger(__name__)

ALGORITHM = "HS256"
TOKEN_EXPIRE_DAYS = 30


@dataclass
class User:
    """Authenticated user context."""
    user_id: str
    email: str
    name: str = ""
    picture: str = ""


# Default fallback user for unauthenticated local development
LOCAL_USER = User(
    user_id="local",
    email="local@wayfarer.app",
    name="Local User",
    picture="",
)


def create_access_token(
    user_id: str,
    email: str,
    name: str = "",
    picture: str = "",
    expires_delta: timedelta | None = None,
) -> str:
    """Generate a signed JWT access token for session management."""
    now = datetime.now(timezone.utc)
    delta = expires_delta or timedelta(days=TOKEN_EXPIRE_DAYS)
    payload = {
        "sub": user_id,
        "email": email,
        "name": name,
        "picture": picture,
        "iat": int(now.timestamp()),
        "exp": int((now + delta).timestamp()),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any] | None:
    """Decode and verify a JWT access token."""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError as exc:
        logger.debug("JWT decode failed: %s", exc)
        return None


async def verify_google_id_token(id_token: str) -> dict[str, str]:
    """Verify a Google OAuth ID token via Google's tokeninfo API."""
    url = f"https://oauth2.googleapis.com/tokeninfo?id_token={id_token}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url)
        if resp.status_code != 200:
            raise ValueError(f"Google token verification failed: {resp.text}")
        data = resp.json()
        
        # Verify audience if OAUTH_GOOGLE_CLIENT_ID is configured
        if settings.OAUTH_GOOGLE_CLIENT_ID:
            aud = data.get("aud")
            if aud != settings.OAUTH_GOOGLE_CLIENT_ID:
                raise ValueError("Google token client ID mismatch")

        user_id = data.get("sub", "")
        email = data.get("email", "")
        name = data.get("name", email.split("@")[0] if email else "Google User")
        picture = data.get("picture", "")

        if not user_id or not email:
            raise ValueError("Google token missing required claims (sub, email)")

        return {
            "user_id": f"google_{user_id}",
            "email": email,
            "name": name,
            "picture": picture,
        }


async def get_current_user(request: Request) -> User:
    """FastAPI dependency extracting current user from Bearer header or fallback."""
    auth_header = request.headers.get("Authorization") or ""
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        payload = decode_access_token(token)
        if payload and "sub" in payload:
            user_id = payload["sub"]
            email = payload.get("email", "")
            name = payload.get("name", "")
            picture = payload.get("picture", "")

            # Ensure user exists in SQLite DB
            upsert_user(user_id=user_id, email=email, name=name, picture=picture)
            return User(user_id=user_id, email=email, name=name, picture=picture)

    # Fallback to local user if unauthenticated
    return LOCAL_USER
