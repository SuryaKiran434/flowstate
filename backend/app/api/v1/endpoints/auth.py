"""
Auth Endpoints — Flowstate
---------------------------
Spotify OAuth2 PKCE flow:

GET  /api/v1/auth/spotify/login     → returns Spotify authorization URL
GET  /api/v1/auth/spotify/callback  → handles redirect, issues JWT
GET  /api/v1/auth/me                → returns current user profile
"""

import os
import uuid
import redis as redis_lib
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import create_access_token, get_current_user_id
from app.db.session import get_db
from app.models.user import User
from app.services.spotify_client import (
    build_auth_url,
    exchange_code_for_tokens,
    generate_code_challenge,
    generate_code_verifier,
    get_spotify_user_profile,
    token_expires_at,
)

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()

# Redis-backed PKCE verifier store — keyed by state UUID, expires after 10 minutes.
# Replaces the previous in-memory dict which leaked on abandoned logins and
# was lost on server restart.
_redis = redis_lib.Redis.from_url(settings.redis_url, decode_responses=True)
_PKCE_TTL = 600  # seconds — standard OAuth state lifetime


@router.get("/spotify/login")
async def spotify_login():
    """
    Step 1: Generate Spotify authorization URL with PKCE.
    Frontend should redirect the user to the returned auth_url.
    """
    state = str(uuid.uuid4())
    code_verifier = generate_code_verifier()
    code_challenge = generate_code_challenge(code_verifier)

    # Store verifier in Redis — expires automatically after _PKCE_TTL seconds
    _redis.setex(f"pkce:{state}", _PKCE_TTL, code_verifier)

    auth_url = build_auth_url(state=state, code_challenge=code_challenge)

    return {
        "auth_url": auth_url,
        "state": state,
    }


@router.get("/spotify/callback")
async def spotify_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: Session = Depends(get_db),
):
    """
    Step 2: Spotify redirects here with authorization code.
    - Validates state
    - Exchanges code + PKCE verifier for tokens
    - Creates or updates user in DB
    - Issues Flowstate JWT
    - Redirects frontend to /dashboard with token in query param
    """
    # Validate state and retrieve PKCE verifier — atomic get-and-delete
    code_verifier = _redis.getdel(f"pkce:{state}")
    if not code_verifier:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired state parameter",
        )

    # Exchange authorization code for Spotify tokens
    try:
        token_data = await exchange_code_for_tokens(
            code=code,
            code_verifier=code_verifier,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to exchange code for tokens: {str(e)}",
        )

    access_token = token_data["access_token"]
    refresh_token = token_data.get("refresh_token")
    expires_in = token_data.get("expires_in", 3600)

    # Fetch Spotify user profile
    try:
        profile = await get_spotify_user_profile(access_token)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to fetch Spotify profile: {str(e)}",
        )

    spotify_id = profile["id"]
    display_name = profile.get("display_name", "")
    email = profile.get("email", "")

    # Upsert user in database
    user = db.query(User).filter(User.spotify_id == spotify_id).first()
    if user:
        user.display_name = display_name
        user.email = email
        user.access_token = access_token
        if refresh_token:
            user.refresh_token = refresh_token
        user.token_expires_at = token_expires_at(expires_in)
    else:
        user = User(
            spotify_id=spotify_id,
            display_name=display_name,
            email=email,
            access_token=access_token,
            refresh_token=refresh_token,
            token_expires_at=token_expires_at(expires_in),
        )
        db.add(user)

    db.commit()
    db.refresh(user)

    # Issue Flowstate JWT
    flowstate_token = create_access_token(data={"sub": str(user.id)})

    # Redirect frontend with token
    frontend_url = "http://localhost:3000"
    return RedirectResponse(
        url=f"{frontend_url}/dashboard?token={flowstate_token}",
        status_code=302,
    )


@router.get("/me")
async def get_me(
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """
    Returns the currently authenticated user's profile.
    Requires Bearer token in Authorization header.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    return {
        "id": str(user.id),
        "spotify_id": user.spotify_id,
        "display_name": user.display_name,
        "email": user.email,
        "created_at": user.created_at,
    }
