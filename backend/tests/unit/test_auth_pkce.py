"""
Unit tests for Redis-backed PKCE store in app/api/v1/endpoints/auth.py

Verifies that:
- spotify_login stores the verifier in Redis with the correct key, TTL, and value
- spotify_callback retrieves and atomically deletes the verifier via getdel
- An invalid or expired state causes a 400 response
- Each login generates a unique Redis key
- getdel is called exactly once per callback (verifier is consumed, not reusable)
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest
from fastapi import HTTPException

import app.api.v1.endpoints.auth as auth_module
from app.api.v1.endpoints.auth import _PKCE_TTL, spotify_callback, spotify_login


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _mock_redis():
    """Return a MagicMock that stands in for the module-level _redis client."""
    m = MagicMock()
    m.setex = MagicMock(return_value=True)
    m.getdel = MagicMock(return_value=None)
    return m


# ─── spotify_login — Redis write behaviour ────────────────────────────────────

class TestLoginRedisWrite:
    async def test_setex_called_once(self):
        mock_redis = _mock_redis()
        with patch.object(auth_module, "_redis", mock_redis):
            await spotify_login()
        mock_redis.setex.assert_called_once()

    async def test_key_has_pkce_prefix(self):
        mock_redis = _mock_redis()
        with patch.object(auth_module, "_redis", mock_redis):
            result = await spotify_login()

        state = result["state"]
        key_used = mock_redis.setex.call_args[0][0]
        assert key_used == f"pkce:{state}"

    async def test_ttl_is_pkce_ttl_constant(self):
        mock_redis = _mock_redis()
        with patch.object(auth_module, "_redis", mock_redis):
            await spotify_login()

        ttl_used = mock_redis.setex.call_args[0][1]
        assert ttl_used == _PKCE_TTL
        assert ttl_used == 600

    async def test_value_stored_is_nonempty_string(self):
        mock_redis = _mock_redis()
        with patch.object(auth_module, "_redis", mock_redis):
            await spotify_login()

        verifier_stored = mock_redis.setex.call_args[0][2]
        assert isinstance(verifier_stored, str)
        assert len(verifier_stored) > 0

    async def test_returns_auth_url_and_state(self):
        mock_redis = _mock_redis()
        with patch.object(auth_module, "_redis", mock_redis):
            result = await spotify_login()

        assert "auth_url" in result
        assert "state" in result
        assert len(result["state"]) > 0

    async def test_each_login_uses_unique_key(self):
        mock_redis = _mock_redis()
        with patch.object(auth_module, "_redis", mock_redis):
            r1 = await spotify_login()
            r2 = await spotify_login()

        assert r1["state"] != r2["state"]
        calls = mock_redis.setex.call_args_list
        key1 = calls[0][0][0]
        key2 = calls[1][0][0]
        assert key1 != key2


# ─── spotify_callback — Redis read behaviour ──────────────────────────────────

class TestCallbackRedisRead:
    async def test_getdel_called_with_correct_key(self):
        mock_redis = _mock_redis()
        mock_redis.getdel.return_value = "some-verifier"

        # Stub everything past the PKCE lookup so the test stays focused
        with patch.object(auth_module, "_redis", mock_redis), \
             patch("app.api.v1.endpoints.auth.exchange_code_for_tokens",
                   new=AsyncMock(return_value={
                       "access_token": "tok", "refresh_token": "ref", "expires_in": 3600
                   })), \
             patch("app.api.v1.endpoints.auth.get_spotify_user_profile",
                   new=AsyncMock(return_value={
                       "id": "spotify123", "display_name": "Test", "email": "t@t.com"
                   })), \
             patch("app.api.v1.endpoints.auth.create_access_token",
                   return_value="jwt-token"), \
             patch("app.api.v1.endpoints.auth.token_expires_at",
                   return_value="2099-01-01"):

            mock_db = MagicMock()
            mock_db.query.return_value.filter.return_value.first.return_value = None

            state = "test-state-uuid"
            try:
                await spotify_callback(code="auth-code", state=state, db=mock_db)
            except Exception:
                pass  # RedirectResponse raises in test context — we only care about getdel

        mock_redis.getdel.assert_called_once_with(f"pkce:{state}")

    async def test_invalid_state_raises_http_400(self):
        mock_redis = _mock_redis()
        mock_redis.getdel.return_value = None  # state not found / expired

        with patch.object(auth_module, "_redis", mock_redis):
            mock_db = MagicMock()
            with pytest.raises(HTTPException) as exc_info:
                await spotify_callback(code="any", state="bogus-state", db=mock_db)

        assert exc_info.value.status_code == 400
        assert "expired" in exc_info.value.detail.lower() or \
               "invalid" in exc_info.value.detail.lower()

    async def test_getdel_called_exactly_once(self):
        """Verifier is consumed in a single atomic call — not get then delete."""
        mock_redis = _mock_redis()
        mock_redis.getdel.return_value = None  # triggers 400, but call count is what matters

        with patch.object(auth_module, "_redis", mock_redis):
            mock_db = MagicMock()
            with pytest.raises(HTTPException):
                await spotify_callback(code="c", state="s", db=mock_db)

        mock_redis.getdel.assert_called_once()

    async def test_get_and_delete_are_not_called_separately(self):
        """Ensure we're not using get() + delete() — must use atomic getdel()."""
        mock_redis = _mock_redis()
        mock_redis.getdel.return_value = None

        with patch.object(auth_module, "_redis", mock_redis):
            mock_db = MagicMock()
            with pytest.raises(HTTPException):
                await spotify_callback(code="c", state="s", db=mock_db)

        mock_redis.get.assert_not_called()
        mock_redis.delete.assert_not_called()


# ─── TTL constant ─────────────────────────────────────────────────────────────

class TestPkceTtlConstant:
    def test_pkce_ttl_is_ten_minutes(self):
        assert _PKCE_TTL == 600

    def test_pkce_ttl_is_int(self):
        assert isinstance(_PKCE_TTL, int)
