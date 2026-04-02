"""
Spotify OAuth2 PKCE Service
----------------------------
Handles the full Spotify authorization code flow with PKCE,
plus helper methods for fetching the user's personal library:
  - Playlists + their tracks
  - Liked/saved tracks
  - Top tracks and artists
  - Followed artists
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
    from urllib.parse import urlencode

    params = {
        "client_id": settings.spotify_client_id,
        "response_type": "code",
        "redirect_uri": settings.spotify_redirect_uri,
        "state": state,
        "scope": settings.spotify_scopes,
        "code_challenge_method": "S256",
        "code_challenge": code_challenge,
    }
    return f"{settings.spotify_auth_url}?{urlencode(params)}"


async def exchange_code_for_tokens(code: str, code_verifier: str) -> dict:
    """Exchange the authorization code + PKCE verifier for access/refresh tokens."""
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
    """Use the refresh token to get a new access token."""
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


# ── Personal Library Helpers (used by Airflow DAG) ────────────────────────────


async def get_user_playlists(access_token: str) -> list[dict]:
    """
    Fetch all of the current user's playlists (public + private).
    Requires: playlist-read-private scope.
    Handles pagination automatically.
    """
    playlists = []
    url = "https://api.spotify.com/v1/me/playlists"
    params = {"limit": 50}

    async with httpx.AsyncClient() as client:
        while url:
            resp = await client.get(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
                params=params,
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            playlists.extend(data.get("items", []))
            url = data.get("next")
            params = {}  # next URL already has params

    return [p for p in playlists if p]  # filter nulls


async def get_playlist_tracks(access_token: str, playlist_id: str) -> list[dict]:
    """
    Fetch all tracks from a playlist.
    Requires: playlist-read-private scope.
    Handles pagination automatically.
    """
    tracks = []
    url = f"https://api.spotify.com/v1/playlists/{playlist_id}/items"
    params = {
        "limit": 50,
        "fields": "next,items(track(id,name,artists,album,duration_ms,preview_url,popularity))",
    }

    async with httpx.AsyncClient() as client:
        while url:
            resp = await client.get(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
                params=params,
                timeout=15,
            )
            if resp.status_code == 403:
                # Skip playlists we can't access
                break
            resp.raise_for_status()
            data = resp.json()
            for item in data.get("items", []):
                track = item.get("track") if item else None
                if track and track.get("id"):
                    tracks.append(track)
            url = data.get("next")
            params = {}

    return tracks


async def get_liked_tracks(access_token: str, limit: int = 200) -> list[dict]:
    """
    Fetch the user's saved/liked tracks.
    Requires: user-library-read scope.
    """
    tracks = []
    url = "https://api.spotify.com/v1/me/tracks"
    params = {"limit": 50}
    fetched = 0

    async with httpx.AsyncClient() as client:
        while url and fetched < limit:
            resp = await client.get(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
                params=params,
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            for item in data.get("items", []):
                track = item.get("track") if item else None
                if track and track.get("id"):
                    tracks.append(track)
                    fetched += 1
            url = data.get("next")
            params = {}

    return tracks


async def get_top_tracks(
    access_token: str, time_range: str = "medium_term"
) -> list[dict]:
    """
    Fetch the user's top tracks.
    Requires: user-top-read scope.
    time_range: short_term (4 weeks), medium_term (6 months), long_term (all time)
    """
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://api.spotify.com/v1/me/top/tracks",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"limit": 50, "time_range": time_range},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get("items", [])


async def get_top_artists(
    access_token: str, time_range: str = "medium_term"
) -> list[dict]:
    """
    Fetch the user's top artists, then get their top tracks.
    Requires: user-top-read scope.
    """
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://api.spotify.com/v1/me/top/artists",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"limit": 20, "time_range": time_range},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get("items", [])


async def get_artist_top_tracks(access_token: str, artist_id: str) -> list[dict]:
    """Get top tracks for a specific artist."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://api.spotify.com/v1/artists/{artist_id}/top-tracks",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"market": "US"},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get("tracks", [])
