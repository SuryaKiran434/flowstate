/**
 * SpotifyPlayer — Flowstate
 * ---------------------------
 * In-app Spotify playback via the Web Playback SDK.
 *
 * Props:
 *   tracks        {Array}   Flat track list from arc.tracks
 *                           Each: { spotify_id, title, artist, duration_ms, emotion_label, energy }
 *   spotifyToken  {string}  Spotify OAuth access token (from GET /auth/spotify-token)
 *   onTrackChange {fn}      Called with (index) whenever the active track changes
 *
 * Exposed via ref:
 *   ref.current.playFromIndex(index)  — start playback from a specific track index
 *
 * Requirements:
 *   - Spotify Premium account (SDK limitation — non-Premium shows fallback)
 *   - Tokens with scopes: streaming, user-read-playback-state, user-modify-playback-state
 */

import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from 'react'

const EMOTION_COLORS = {
  energetic: '#f59e0b', happy: '#10b981', euphoric: '#8b5cf6',
  peaceful: '#06b6d4', focused: '#3b82f6', romantic: '#ec4899',
  nostalgic: '#f97316', neutral: '#6b7280', melancholic: '#6366f1',
  sad: '#94a3b8', tense: '#ef4444', angry: '#dc2626',
}

function fmtMs(ms) {
  if (!ms || ms < 0) return '0:00'
  const s = Math.floor(ms / 1000)
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

const SpotifyPlayer = forwardRef(function SpotifyPlayer(
  { tracks = [], spotifyToken, onTrackChange },
  ref,
) {
  const [deviceId, setDeviceId]       = useState(null)
  const [playerReady, setPlayerReady] = useState(false)
  const [currentIndex, setCurrentIndex] = useState(0)
  const [isPaused, setIsPaused]       = useState(true)
  const [position, setPosition]       = useState(0)
  const [duration, setDuration]       = useState(0)
  const [error, setError]             = useState(null)  // null | 'premium_required' | 'auth_error'
  const [loading, setLoading]         = useState(true)

  const playerRef   = useRef(null)
  const intervalRef = useRef(null)
  const deviceIdRef = useRef(null)  // keep stable reference for async callbacks

  // ── Sync deviceId to ref so async callbacks can read it ────────────────────
  useEffect(() => { deviceIdRef.current = deviceId }, [deviceId])

  // ── Load Spotify SDK script and initialize player ───────────────────────────
  useEffect(() => {
    if (!spotifyToken || !tracks.length) return

    // SDK script only needs to be injected once per page
    const SCRIPT_ID = 'spotify-sdk-script'
    if (!document.getElementById(SCRIPT_ID)) {
      const script = document.createElement('script')
      script.id    = SCRIPT_ID
      script.src   = 'https://sdk.scdn.co/spotify-player.js'
      script.async = true
      document.body.appendChild(script)
    }

    window.onSpotifyWebPlaybackSDKReady = () => {
      const player = new window.Spotify.Player({
        name: 'Flowstate',
        getOAuthToken: cb => cb(spotifyToken),
        volume: 0.8,
      })

      player.addListener('ready', ({ device_id }) => {
        setDeviceId(device_id)
        setPlayerReady(true)
        setLoading(false)
      })

      player.addListener('not_ready', () => {
        setPlayerReady(false)
      })

      player.addListener('player_state_changed', state => {
        if (!state) return
        setIsPaused(state.paused)
        setPosition(state.position)
        setDuration(state.duration)

        // Sync currentIndex by matching the playing URI to our track list
        const uri = state.track_window?.current_track?.uri
        if (uri) {
          const idx = tracks.findIndex(t => `spotify:track:${t.spotify_id}` === uri)
          if (idx !== -1 && idx !== currentIndex) {
            setCurrentIndex(idx)
            onTrackChange?.(idx)
          }
        }
      })

      player.addListener('authentication_error', () => {
        setError('auth_error')
        setLoading(false)
      })

      player.addListener('account_error', () => {
        setError('premium_required')
        setLoading(false)
      })

      player.addListener('initialization_error', () => {
        setError('init_error')
        setLoading(false)
      })

      player.connect()
      playerRef.current = player
    }

    // If SDK is already loaded, fire the callback immediately
    if (window.Spotify) {
      window.onSpotifyWebPlaybackSDKReady()
    }

    return () => {
      if (playerRef.current) {
        playerRef.current.disconnect()
        playerRef.current = null
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [spotifyToken])

  // ── Progress ticker — increments position every second when playing ─────────
  useEffect(() => {
    clearInterval(intervalRef.current)
    if (!isPaused) {
      intervalRef.current = setInterval(() => {
        setPosition(p => Math.min(p + 1000, duration))
      }, 1000)
    }
    return () => clearInterval(intervalRef.current)
  }, [isPaused, duration])

  // ── Playback control: start queue from a given index ────────────────────────
  const playFromIndex = useCallback(async (index) => {
    const did = deviceIdRef.current
    if (!did || !spotifyToken) return
    const uris = tracks.slice(index).map(t => `spotify:track:${t.spotify_id}`)
    try {
      await fetch(
        `https://api.spotify.com/v1/me/player/play?device_id=${did}`,
        {
          method: 'PUT',
          headers: {
            Authorization: `Bearer ${spotifyToken}`,
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ uris }),
        },
      )
      setCurrentIndex(index)
      setIsPaused(false)
      onTrackChange?.(index)
    } catch {
      // network failure — ignore, user can retry
    }
  }, [tracks, spotifyToken, onTrackChange])

  // ── Expose playFromIndex to parent via ref ──────────────────────────────────
  useImperativeHandle(ref, () => ({ playFromIndex, currentIndex }), [playFromIndex, currentIndex])

  // ── Control helpers ─────────────────────────────────────────────────────────
  const togglePlay = () => playerRef.current?.togglePlay()
  const previous   = () => playerRef.current?.previousTrack()
  const next       = () => playerRef.current?.nextTrack()
  const seek       = (e) => {
    const pct = parseFloat(e.target.value) / 100
    const ms  = Math.floor(pct * duration)
    playerRef.current?.seek(ms)
    setPosition(ms)
  }

  // ── Styles ─────────────────────────────────────────────────────────────────
  const bar = {
    position: 'fixed',
    bottom: 0, left: 0, right: 0,
    background: 'rgba(10, 6, 20, 0.97)',
    backdropFilter: 'blur(20px)',
    borderTop: '1px solid rgba(139, 92, 246, 0.25)',
    padding: '0 24px',
    zIndex: 1000,
    display: 'flex',
    flexDirection: 'column',
    gap: 0,
  }
  const trackInfo = {
    color: '#e2e8f0',
    fontSize: 13,
    fontWeight: 500,
    whiteSpace: 'nowrap',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    maxWidth: 260,
  }
  const btn = (active) => ({
    background: 'none',
    border: 'none',
    cursor: 'pointer',
    color: active ? '#a78bfa' : '#94a3b8',
    fontSize: active ? 22 : 18,
    padding: '0 8px',
    transition: 'color 0.15s',
    lineHeight: 1,
  })
  const progressWrap = {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    paddingBottom: 8,
  }
  const timeLabel = { color: '#64748b', fontSize: 11, minWidth: 36 }

  const currentTrack = tracks[currentIndex]
  const trackColor   = EMOTION_COLORS[currentTrack?.emotion_label] || '#8b5cf6'
  const pct          = duration > 0 ? (position / duration) * 100 : 0

  // ── Fallback: non-Premium ───────────────────────────────────────────────────
  if (error === 'premium_required') {
    return (
      <div style={{ ...bar, padding: '12px 24px', flexDirection: 'row', alignItems: 'center', gap: 12 }}>
        <span style={{ fontSize: 16 }}>🎵</span>
        <span style={{ color: '#94a3b8', fontSize: 13 }}>
          Spotify Premium required for in-app playback — click any track to open in Spotify
        </span>
      </div>
    )
  }

  // ── Connecting state ────────────────────────────────────────────────────────
  if (loading || !playerReady) {
    return (
      <div style={{ ...bar, padding: '14px 24px', flexDirection: 'row', alignItems: 'center', gap: 10 }}>
        <span style={{ color: '#64748b', fontSize: 13 }}>
          {error ? `Player error — ${error}` : 'Connecting to Spotify…'}
        </span>
      </div>
    )
  }

  // ── Player bar ──────────────────────────────────────────────────────────────
  return (
    <div style={bar}>
      {/* Top row: track info + controls */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 16, padding: '10px 0 6px' }}>
        {/* Track color indicator */}
        <div style={{
          width: 4, height: 36, borderRadius: 2,
          background: trackColor, flexShrink: 0,
        }} />

        {/* Track name + artist */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={trackInfo}>{currentTrack?.title || '—'}</div>
          <div style={{ ...trackInfo, fontSize: 11, color: '#64748b', fontWeight: 400, marginTop: 2 }}>
            {currentTrack?.artist || ''}
          </div>
        </div>

        {/* Controls */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 4, flexShrink: 0 }}>
          <button style={btn(false)} onClick={previous} title="Previous">⏮</button>
          <button
            style={{ ...btn(true), fontSize: 26, color: trackColor }}
            onClick={togglePlay}
            title={isPaused ? 'Play' : 'Pause'}
          >
            {isPaused ? '▶' : '⏸'}
          </button>
          <button style={btn(false)} onClick={next} title="Next">⏭</button>
        </div>

        {/* Track counter */}
        <div style={{ color: '#475569', fontSize: 11, flexShrink: 0, minWidth: 48, textAlign: 'right' }}>
          {currentIndex + 1} / {tracks.length}
        </div>
      </div>

      {/* Progress row */}
      <div style={progressWrap}>
        <span style={timeLabel}>{fmtMs(position)}</span>
        <input
          type="range"
          min="0"
          max="100"
          value={pct.toFixed(1)}
          onChange={seek}
          style={{
            flex: 1,
            height: 3,
            cursor: 'pointer',
            accentColor: trackColor,
            background: `linear-gradient(to right, ${trackColor} ${pct}%, rgba(100,116,139,0.3) ${pct}%)`,
          }}
        />
        <span style={{ ...timeLabel, textAlign: 'right' }}>{fmtMs(duration)}</span>
      </div>
    </div>
  )
})

export default SpotifyPlayer
