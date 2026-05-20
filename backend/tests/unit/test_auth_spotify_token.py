"""
Unit tests for GET /auth/spotify-token in app/api/v1/endpoints/auth.py

Verifies:
- Returns access_token for a valid user with a fresh token
- Refreshes the token when it has expired
- Refreshes proactively when expiring within 5 minutes
- Does NOT refresh when refresh_token is missing
- Returns 404 when the user is not found
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

import app.api.v1.endpoints.auth as auth_module
from app.api.v1.endpoints.auth import get_spotify_token


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_user(
    access_token: str = "fresh-spotify-tok",
    refresh_token: str = "refresh-tok",
    token_expires_at=None,
) -> MagicMock:
    user = MagicMock()
    user.access_token   = access_token
    user.refresh_token  = refresh_token
    user.token_expires_at = token_expires_at
    return user


def _make_db(user=None) -> MagicMock:
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = user
    return db


def _future(minutes: int) -> datetime:
    return datetime.utcnow() + timedelta(minutes=minutes)


def _past(minutes: int = 60) -> datetime:
    return datetime.utcnow() - timedelta(minutes=minutes)


# ─── Tests ────────────────────────────────────────────────────────────────────

class TestGetSpotifyToken:
    async def test_returns_access_token_for_valid_user(self):
        user = _make_user(
            access_token="valid-tok",
            token_expires_at=_future(60),  # expires in 1 hour — no refresh needed
        )
        db = _make_db(user)

        with patch("app.api.v1.endpoints.auth.refresh_access_token") as mock_refresh:
            result = await get_spotify_token(user_id="uid-1", db=db)

        mock_refresh.assert_not_called()
        assert result["access_token"] == "valid-tok"

    async def test_refreshes_expired_token(self):
        user = _make_user(
            access_token="old-tok",
            refresh_token="refresh-tok",
            token_expires_at=_past(10),  # expired 10 minutes ago
        )
        db = _make_db(user)

        new_token_data = {
            "access_token": "new-tok",
            "refresh_token": "new-refresh",
            "expires_in": 3600,
        }
        with patch(
            "app.api.v1.endpoints.auth.refresh_access_token",
            new=AsyncMock(return_value=new_token_data),
        ):
            result = await get_spotify_token(user_id="uid-1", db=db)

        assert result["access_token"] == "new-tok"
        assert user.access_token == "new-tok"
        assert user.refresh_token == "new-refresh"
        db.commit.assert_called_once()

    async def test_refreshes_token_expiring_within_5_minutes(self):
        user = _make_user(
            access_token="soon-expiring-tok",
            refresh_token="refresh-tok",
            token_expires_at=_future(3),  # expires in 3 min — within the 5-min window
        )
        db = _make_db(user)

        new_token_data = {"access_token": "refreshed-tok", "expires_in": 3600}
        with patch(
            "app.api.v1.endpoints.auth.refresh_access_token",
            new=AsyncMock(return_value=new_token_data),
        ):
            result = await get_spotify_token(user_id="uid-1", db=db)

        assert result["access_token"] == "refreshed-tok"

    async def test_does_not_refresh_token_with_plenty_of_time(self):
        user = _make_user(
            access_token="long-lived-tok",
            token_expires_at=_future(30),  # expires in 30 min — no refresh
        )
        db = _make_db(user)

        with patch("app.api.v1.endpoints.auth.refresh_access_token") as mock_refresh:
            result = await get_spotify_token(user_id="uid-1", db=db)

        mock_refresh.assert_not_called()
        assert result["access_token"] == "long-lived-tok"

    async def test_serves_existing_token_when_no_refresh_token(self):
        user = _make_user(
            access_token="stale-tok",
            refresh_token=None,             # no refresh token available
            token_expires_at=_past(30),     # expired but can't refresh
        )
        db = _make_db(user)

        with patch("app.api.v1.endpoints.auth.refresh_access_token") as mock_refresh:
            result = await get_spotify_token(user_id="uid-1", db=db)

        mock_refresh.assert_not_called()
        assert result["access_token"] == "stale-tok"

    async def test_raises_401_when_refresh_fails_on_expired_token(self):
        # Token is already expired AND refresh failed → can't serve a broken
        # token to the SDK silently; frontend must re-auth.
        user = _make_user(
            access_token="fallback-tok",
            refresh_token="refresh-tok",
            token_expires_at=_past(10),
        )
        db = _make_db(user)

        with patch(
            "app.api.v1.endpoints.auth.refresh_access_token",
            new=AsyncMock(side_effect=Exception("Spotify API down")),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await get_spotify_token(user_id="uid-1", db=db)

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "spotify_refresh_failed"

    async def test_warns_when_refresh_fails_but_token_still_valid(self):
        # Token expires soon (within 5 min) but is not yet expired; refresh
        # failed. Serve the still-valid token with a warning so the frontend
        # can preemptively re-auth before it actually expires.
        user = _make_user(
            access_token="still-valid-tok",
            refresh_token="refresh-tok",
            token_expires_at=_future(2),  # 2 minutes from now — needs refresh
        )
        db = _make_db(user)

        with patch(
            "app.api.v1.endpoints.auth.refresh_access_token",
            new=AsyncMock(side_effect=Exception("Spotify API down")),
        ):
            result = await get_spotify_token(user_id="uid-1", db=db)

        assert result["access_token"] == "still-valid-tok"
        assert result.get("refresh_warning") == "spotify_refresh_failed"

    async def test_404_if_user_not_found(self):
        db = _make_db(user=None)

        with pytest.raises(HTTPException) as exc_info:
            await get_spotify_token(user_id="nonexistent", db=db)

        assert exc_info.value.status_code == 404

    async def test_new_refresh_token_stored_when_provided(self):
        user = _make_user(
            access_token="old-tok",
            refresh_token="old-refresh",
            token_expires_at=_past(5),
        )
        db = _make_db(user)

        with patch(
            "app.api.v1.endpoints.auth.refresh_access_token",
            new=AsyncMock(return_value={
                "access_token": "new-tok",
                "refresh_token": "brand-new-refresh",
                "expires_in": 3600,
            }),
        ):
            await get_spotify_token(user_id="uid-1", db=db)

        assert user.refresh_token == "brand-new-refresh"

    async def test_refresh_token_unchanged_when_not_in_response(self):
        """Some Spotify refresh responses omit refresh_token — keep existing one."""
        user = _make_user(
            access_token="old-tok",
            refresh_token="keep-this-refresh",
            token_expires_at=_past(5),
        )
        db = _make_db(user)

        with patch(
            "app.api.v1.endpoints.auth.refresh_access_token",
            new=AsyncMock(return_value={
                "access_token": "new-tok",
                # no refresh_token in response
                "expires_in": 3600,
            }),
        ):
            await get_spotify_token(user_id="uid-1", db=db)

        assert user.refresh_token == "keep-this-refresh"
