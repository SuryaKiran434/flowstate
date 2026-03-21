"""
Unit tests for app/services/library_seeder.py

Verifies that:
- Playlists and top tracks are fetched from correct Spotify API calls
- Tracks from multiple sources are deduplicated
- tracks table is upserted with correct SQL
- user_tracks table is upserted with correct user_id
- Return value is an integer count
- Empty library (no playlists, no top tracks) returns 0 without crashing
- Tracks missing an 'id' field are silently skipped
"""

from unittest.mock import AsyncMock, MagicMock, patch

from app.services.library_seeder import seed_user_library


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_track(tid: str, name: str = "Track") -> dict:
    return {
        "id": tid,
        "name": name,
        "artists": [{"name": "Artist"}],
        "album": {"name": "Album"},
        "duration_ms": 200000,
        "preview_url": None,
        "popularity": 50,
    }


def _make_db():
    """Return a MagicMock that stands in for a SQLAlchemy session."""
    db = MagicMock()
    db.execute = MagicMock()
    db.commit = MagicMock()
    return db


PLAYLISTS = [{"id": "pl1"}, {"id": "pl2"}]
PLAYLIST_TRACKS = {
    "pl1": [_make_track("t1"), _make_track("t2")],
    "pl2": [_make_track("t3")],
}
TOP_TRACKS = {
    "short_term":  [_make_track("t4"), _make_track("t5")],
    "medium_term": [_make_track("t6")],
    "long_term":   [_make_track("t1")],  # duplicate of t1 from playlist
}


async def _get_playlist_tracks(access_token, playlist_id):
    return PLAYLIST_TRACKS.get(playlist_id, [])


async def _get_top_tracks(access_token, time_range):
    return TOP_TRACKS.get(time_range, [])


# ─── Tests ────────────────────────────────────────────────────────────────────

class TestSeedCallsSpotifyAPIs:
    async def test_calls_get_user_playlists(self):
        mock_playlists = AsyncMock(return_value=PLAYLISTS)
        mock_playlist_tracks = AsyncMock(side_effect=_get_playlist_tracks)
        mock_top_tracks = AsyncMock(side_effect=_get_top_tracks)

        with patch("app.services.library_seeder.get_user_playlists", mock_playlists), \
             patch("app.services.library_seeder.get_playlist_tracks", mock_playlist_tracks), \
             patch("app.services.library_seeder.get_top_tracks", mock_top_tracks):
            await seed_user_library("user-1", "tok", _make_db())

        mock_playlists.assert_called_once_with("tok")

    async def test_calls_get_playlist_tracks_for_each_playlist(self):
        mock_playlists = AsyncMock(return_value=PLAYLISTS)
        mock_playlist_tracks = AsyncMock(side_effect=_get_playlist_tracks)
        mock_top_tracks = AsyncMock(side_effect=_get_top_tracks)

        with patch("app.services.library_seeder.get_user_playlists", mock_playlists), \
             patch("app.services.library_seeder.get_playlist_tracks", mock_playlist_tracks), \
             patch("app.services.library_seeder.get_top_tracks", mock_top_tracks):
            await seed_user_library("user-1", "tok", _make_db())

        assert mock_playlist_tracks.call_count == len(PLAYLISTS)
        mock_playlist_tracks.assert_any_call("tok", "pl1")
        mock_playlist_tracks.assert_any_call("tok", "pl2")

    async def test_calls_top_tracks_for_all_three_time_ranges(self):
        mock_playlists = AsyncMock(return_value=[])
        mock_top_tracks = AsyncMock(side_effect=_get_top_tracks)

        with patch("app.services.library_seeder.get_user_playlists", mock_playlists), \
             patch("app.services.library_seeder.get_playlist_tracks", AsyncMock(return_value=[])), \
             patch("app.services.library_seeder.get_top_tracks", mock_top_tracks):
            await seed_user_library("user-1", "tok", _make_db())

        # time_range is passed as a keyword argument
        ranges_called = {
            c.args[1] if len(c.args) > 1 else c.kwargs.get("time_range")
            for c in mock_top_tracks.call_args_list
        }
        assert ranges_called == {"short_term", "medium_term", "long_term"}


class TestSeedDeduplication:
    async def test_duplicate_track_across_sources_counted_once(self):
        # t1 appears in pl1 AND long_term top tracks
        mock_playlists = AsyncMock(return_value=PLAYLISTS)
        mock_playlist_tracks = AsyncMock(side_effect=_get_playlist_tracks)
        mock_top_tracks = AsyncMock(side_effect=_get_top_tracks)
        db = _make_db()

        with patch("app.services.library_seeder.get_user_playlists", mock_playlists), \
             patch("app.services.library_seeder.get_playlist_tracks", mock_playlist_tracks), \
             patch("app.services.library_seeder.get_top_tracks", mock_top_tracks):
            count = await seed_user_library("user-1", "tok", db)

        # t1,t2,t3 from playlists + t4,t5,t6 from top tracks = 6 unique (t1 from long_term duped)
        assert count == 6

    async def test_same_track_from_two_playlists_counted_once(self):
        # both playlists return the same track
        mock_playlists = AsyncMock(return_value=[{"id": "pl1"}, {"id": "pl2"}])
        mock_playlist_tracks = AsyncMock(return_value=[_make_track("shared")])
        db = _make_db()

        with patch("app.services.library_seeder.get_user_playlists", mock_playlists), \
             patch("app.services.library_seeder.get_playlist_tracks", mock_playlist_tracks), \
             patch("app.services.library_seeder.get_top_tracks", AsyncMock(return_value=[])):
            count = await seed_user_library("user-1", "tok", db)

        assert count == 1


class TestSeedDbUpserts:
    async def test_upserts_tracks_table(self):
        track = _make_track("t99")
        db = _make_db()

        with patch("app.services.library_seeder.get_user_playlists", AsyncMock(return_value=[{"id": "p1"}])), \
             patch("app.services.library_seeder.get_playlist_tracks", AsyncMock(return_value=[track])), \
             patch("app.services.library_seeder.get_top_tracks", AsyncMock(return_value=[])):
            await seed_user_library("user-1", "tok", db)

        # Verify at least one db.execute call contains INSERT INTO tracks
        execute_calls = db.execute.call_args_list
        sql_texts = [str(c.args[0]) for c in execute_calls]
        assert any("INSERT INTO tracks" in s for s in sql_texts)

    async def test_upserts_user_tracks_table(self):
        track = _make_track("t99")
        db = _make_db()

        with patch("app.services.library_seeder.get_user_playlists", AsyncMock(return_value=[{"id": "p1"}])), \
             patch("app.services.library_seeder.get_playlist_tracks", AsyncMock(return_value=[track])), \
             patch("app.services.library_seeder.get_top_tracks", AsyncMock(return_value=[])):
            await seed_user_library("user-1", "tok", db)

        execute_calls = db.execute.call_args_list
        params_list = [c.args[1] for c in execute_calls if len(c.args) > 1]
        # At least one call should include user_id = "user-1"
        assert any(p.get("user_id") == "user-1" for p in params_list)

    async def test_commits_at_end(self):
        db = _make_db()

        with patch("app.services.library_seeder.get_user_playlists", AsyncMock(return_value=[])), \
             patch("app.services.library_seeder.get_top_tracks", AsyncMock(return_value=[])):
            await seed_user_library("user-1", "tok", db)

        db.commit.assert_called_once()


class TestSeedReturnValue:
    async def test_returns_int(self):
        with patch("app.services.library_seeder.get_user_playlists", AsyncMock(return_value=[])), \
             patch("app.services.library_seeder.get_top_tracks", AsyncMock(return_value=[])):
            result = await seed_user_library("user-1", "tok", _make_db())

        assert isinstance(result, int)

    async def test_empty_library_returns_zero(self):
        with patch("app.services.library_seeder.get_user_playlists", AsyncMock(return_value=[])), \
             patch("app.services.library_seeder.get_top_tracks", AsyncMock(return_value=[])):
            result = await seed_user_library("user-1", "tok", _make_db())

        assert result == 0

    async def test_count_equals_unique_tracks(self):
        tracks = [_make_track(f"t{i}") for i in range(5)]
        with patch("app.services.library_seeder.get_user_playlists", AsyncMock(return_value=[])), \
             patch("app.services.library_seeder.get_top_tracks", AsyncMock(return_value=tracks)):
            result = await seed_user_library("user-1", "tok", _make_db())

        assert result == 5


class TestSeedEdgeCases:
    async def test_skips_track_without_id(self):
        bad_track = {"name": "No ID Track", "artists": [], "duration_ms": 0}
        db = _make_db()

        with patch("app.services.library_seeder.get_user_playlists", AsyncMock(return_value=[])), \
             patch("app.services.library_seeder.get_top_tracks", AsyncMock(return_value=[bad_track])):
            result = await seed_user_library("user-1", "tok", db)

        assert result == 0
        # No INSERT should have been executed
        execute_calls = db.execute.call_args_list
        sql_texts = [str(c.args[0]) for c in execute_calls]
        assert not any("INSERT INTO tracks" in s for s in sql_texts)

    async def test_skips_none_track(self):
        db = _make_db()

        with patch("app.services.library_seeder.get_user_playlists", AsyncMock(return_value=[])), \
             patch("app.services.library_seeder.get_top_tracks", AsyncMock(return_value=[None])):
            result = await seed_user_library("user-1", "tok", db)

        assert result == 0

    async def test_graceful_on_playlist_api_failure(self):
        """Seeder should not crash if get_user_playlists raises."""
        db = _make_db()

        with patch("app.services.library_seeder.get_user_playlists",
                   AsyncMock(side_effect=Exception("Spotify down"))), \
             patch("app.services.library_seeder.get_top_tracks", AsyncMock(return_value=[])):
            result = await seed_user_library("user-1", "tok", db)

        assert result == 0

    async def test_graceful_on_top_tracks_api_failure(self):
        """Seeder should not crash if get_top_tracks raises."""
        db = _make_db()

        with patch("app.services.library_seeder.get_user_playlists", AsyncMock(return_value=[])), \
             patch("app.services.library_seeder.get_top_tracks",
                   AsyncMock(side_effect=Exception("Rate limited"))):
            result = await seed_user_library("user-1", "tok", db)

        assert result == 0
