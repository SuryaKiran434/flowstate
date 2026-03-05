"""
Spotify OAuth2 PKCE Service
----------------------------
Handles the full Spotify authorization code flow with PKCE:
1. Generate auth URL + code verifier/challenge
2. Exchange authorization code for tokens
3. Fetch user profile from Spotify API
4. Refresh expired access tokens
"""

import base64
import hashlib
import os
import httpx
from datetime import datetime, timedelta
from app.core.config import get_settings

settings = get_settings()


def generate_code_verifier() -> str:
    """Generate a cryptographically random PKCE code verifier (43-128 chars)."""
    return base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode("utf-8")


def generate_code_challenge(verifier: str) -> str:
    """Derive the PKCE code challenge from the verifier using S256 method."""
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("utf-8")


def build_auth_url(state: str, code_challenge: str) -> str:
    """Build the Spotify authorization URL with PKCE parameters."""
    params = {
        "client_id": settings.spotify_client_id,
        "response_type": "code",
        "redirect_uri": settings.spotify_redirect_uri,
        "state": state,
        "scope": settings.spotify_scopes,
        "code_challenge_method": "S256",
        "code_challenge": code_challenge,
    }
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{settings.spotify_auth_url}?{query}"


async def exchange_code_for_tokens(code: str, code_verifier: str) -> dict:
    """
    Exchange the authorization code + PKCE verifier for access/refresh tokens.
    Returns the full token response from Spotify.
    """
    async with httpx.AsyncClient() as client:
        response = await client.post(
            settings.spotify_token_url,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.spotify_redirect_uri,
                "client_id": settings.spotify_client_id,
                "code_verifier": code_verifier,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()
        return response.json()


async def refresh_access_token(refresh_token: str) -> dict:
    """
    Use the refresh token to get a new access token.
    Returns updated token data.
    """
    async with httpx.AsyncClient() as client:
        response = await client.post(
            settings.spotify_token_url,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": settings.spotify_client_id,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()
        return response.json()


async def get_spotify_user_profile(access_token: str) -> dict:
    """Fetch the authenticated user's Spotify profile."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{settings.spotify_api_base}/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        response.raise_for_status()
        return response.json()


def token_expires_at(expires_in_seconds: int) -> datetime:
    """Calculate token expiry datetime from expires_in seconds."""
    return datetime.utcnow() + timedelta(seconds=expires_in_seconds)
