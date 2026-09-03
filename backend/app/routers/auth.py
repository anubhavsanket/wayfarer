"""OAuth & User Settings API router.

Endpoints:
- POST /api/v1/auth/login    - Authenticate via Google OAuth / Dev login & receive session JWT
- GET  /api/v1/auth/me       - Get current user profile
- GET  /api/v1/user/settings - Get current user's encrypted settings
- POST /api/v1/user/settings - Save current user's settings (encrypted at rest)
"""
from __future__ import annotations

import logging
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr

from ..core.auth import User, get_current_user, create_access_token, verify_google_id_token
from ..db import upsert_user, save_user_settings, get_user_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["auth"])


class OAuthLoginRequest(BaseModel):
    provider: str = "google"
    token: Optional[str] = None
    email: Optional[str] = None
    name: Optional[str] = None
    picture: Optional[str] = None


class OAuthLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    email: str
    name: str
    picture: str


class UserSettingsRequest(BaseModel):
    settings: dict[str, Any]


class UserSettingsResponse(BaseModel):
    user_id: str
    settings: dict[str, Any]


@router.post("/auth/login", response_model=OAuthLoginResponse)
async def auth_login(req: OAuthLoginRequest) -> OAuthLoginResponse:
    user_id: str = ""
    email: str = ""
    name: str = req.name or ""
    picture: str = req.picture or ""

    if req.provider.lower() == "google" and req.token:
        try:
            google_data = await verify_google_id_token(req.token)
            user_id = google_data["user_id"]
            email = google_data["email"]
            name = google_data.get("name", name)
            picture = google_data.get("picture", picture)
        except Exception as exc:
            logger.warning("Google ID token verification failed (%s); fallback to payload", exc)
            if not req.email:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=f"OAuth login failed: {exc}",
                ) from exc
            user_id = f"user_{req.email.replace('@', '_at_')}"
            email = req.email
    elif req.email:
        user_id = f"user_{req.email.replace('@', '_at_')}"
        email = req.email
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either OAuth token or email must be provided.",
        )

    # Upsert user record into DB
    db_user = upsert_user(user_id=user_id, email=email, name=name, picture=picture)
    
    # Create signed session JWT
    access_token = create_access_token(
        user_id=user_id,
        email=email,
        name=name,
        picture=picture,
    )

    return OAuthLoginResponse(
        access_token=access_token,
        token_type="bearer",
        user_id=user_id,
        email=email,
        name=name,
        picture=picture,
    )


@router.get("/auth/me")
async def get_me(user: User = Depends(get_current_user)) -> dict[str, Any]:
    return {
        "user_id": user.user_id,
        "email": user.email,
        "name": user.name,
        "picture": user.picture,
    }


@router.get("/user/settings", response_model=UserSettingsResponse)
async def get_settings(user: User = Depends(get_current_user)) -> UserSettingsResponse:
    user_settings = get_user_settings(user.user_id)
    return UserSettingsResponse(user_id=user.user_id, settings=user_settings)


@router.post("/user/settings", response_model=UserSettingsResponse)
async def update_settings(
    req: UserSettingsRequest,
    user: User = Depends(get_current_user),
) -> UserSettingsResponse:
    save_user_settings(user.user_id, req.settings)
    return UserSettingsResponse(user_id=user.user_id, settings=req.settings)
