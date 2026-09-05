"""
Auth Endpoints — Flowstate
---------------------------
Spotify OAuth2 PKCE flow:

GET  /api/v1/auth/spotify/login     → returns Spotify authorization URL
GET  /api/v1/auth/spotify/callback  → handles redirect, issues JWT
GET  /api/v1/auth/me                → returns current user profile
GET  /api/v1/auth/spotify-token     → returns Spotify access token (auto-refreshes)
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

import httpx
import redis as redis_lib
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import create_access_token, get_current_user_id
from app.db.session import get_db
from app.models.user import User
from app.services.library_seeder import seed_user_library_background
from app.services.spotify_client import (
    build_auth_url,
    exchange_code_for_tokens,
    generate_code_challenge,
    generate_code_verifier,
    get_spotify_user_profile,
    refresh_access_token,
    token_expires_at,
)

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()
logger = logging.getLogger(__name__)

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
    code: Annotated[str, Query()],
    state: Annotated[str, Query()],
    db: Annotated[Session, Depends(get_db)],
    background_tasks: BackgroundTasks = None,
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
    except (httpx.HTTPError, ValueError) as e:
        # httpx.HTTPError covers transport failures and raise_for_status();
        # ValueError covers a non-JSON body from response.json(). Anything else
        # is a bug in our own code and must surface rather than masquerade as a
        # client-side 400.
        logger.warning("spotify token exchange failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to exchange code for tokens: {e!s}",
        ) from e

    access_token = token_data["access_token"]
    refresh_token = token_data.get("refresh_token")
    expires_in = token_data.get("expires_in", 3600)

    # Fetch Spotify user profile
    try:
        profile = await get_spotify_user_profile(access_token)
    except (httpx.HTTPError, ValueError) as e:
        # Same boundary as the token exchange above: transport/HTTP status
        # errors and malformed JSON are the caller-visible failures here.
        logger.warning("spotify profile fetch failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to fetch Spotify profile: {e!s}",
        ) from e

    spotify_id = profile["id"]
    display_name = profile.get("display_name", "")
    email = profile.get("email", "")

    # Upsert user in database
    existing = db.query(User).filter(User.spotify_id == spotify_id).first()
    is_new_user = existing is None

    if existing:
        existing.display_name = display_name
        existing.email = email
        existing.access_token = access_token
        if refresh_token:
            existing.refresh_token = refresh_token
        existing.token_expires_at = token_expires_at(expires_in)
        user = existing
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

    # Seed library in background for new users — runs after response is sent
    if is_new_user and background_tasks is not None:
        background_tasks.add_task(
            seed_user_library_background,
            user_id=str(user.id),
            access_token=access_token,
        )

    # Issue Flowstate JWT
    flowstate_token = create_access_token(data={"sub": str(user.id)})

    # Redirect frontend with token
    return RedirectResponse(
        url=f"{settings.frontend_url}/dashboard?token={flowstate_token}",
        status_code=302,
    )


@router.get("/spotify-token")
async def get_spotify_token(
    user_id: Annotated[str, Depends(get_current_user_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Returns the user's current Spotify access token.
    Auto-refreshes proactively if the token expires within the next 5 minutes.
    Required by the frontend Spotify Web Playback SDK initialization.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    now = datetime.now(timezone.utc)
    # token_expires_at is DateTime(timezone=True), so Postgres returns an aware
    # value while spotify_client.token_expires_at() produces a naive UTC one.
    # Normalise both shapes to aware UTC — the comparison below must never mix
    # naive and aware operands, and a naive stored value is always UTC.
    stored_expiry = user.token_expires_at
    if stored_expiry is None:
        expires_at = now
    elif stored_expiry.tzinfo is None:
        expires_at = stored_expiry.replace(tzinfo=timezone.utc)
    else:
        expires_at = stored_expiry.astimezone(timezone.utc)
    needs_refresh = expires_at < now + timedelta(minutes=5)

    if needs_refresh and user.refresh_token:
        try:
            token_data = await refresh_access_token(user.refresh_token)
            user.access_token = token_data["access_token"]
            if token_data.get("refresh_token"):
                user.refresh_token = token_data["refresh_token"]
            user.token_expires_at = token_expires_at(token_data.get("expires_in", 3600))
            db.commit()
        except Exception:
            # Deliberately broad: refresh can fail for any reason and this
            # endpoint must degrade, never 500. Logged with the traceback so
            # the cause is not swallowed.
            logger.exception("spotify token refresh failed for user %s", user_id)
            # Refresh failed (revoked token, network issue, Spotify outage).
            # Serving the cached token would cause silent playback failures in
            # the Web Playback SDK. Tell the frontend so it can re-auth.
            if expires_at < now:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="spotify_refresh_failed",
                )
            # Token still valid for now — serve it but warn the frontend.
            return {
                "access_token": user.access_token,
                "refresh_warning": "spotify_refresh_failed",
            }

    return {"access_token": user.access_token}


@router.get("/me")
async def get_me(
    user_id: Annotated[str, Depends(get_current_user_id)],
    db: Annotated[Session, Depends(get_db)],
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
