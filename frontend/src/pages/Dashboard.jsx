import React, { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1'

export default function Dashboard() {
  const [user, setUser] = useState(null)
  const [error, setError] = useState(null)
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()

  useEffect(() => {
    // If token arrives as query param from OAuth callback, save it
    const tokenFromUrl = searchParams.get('token')
    if (tokenFromUrl) {
      localStorage.setItem('flowstate_token', tokenFromUrl)
      // Clean the token from the URL without triggering a reload
      window.history.replaceState({}, '', '/dashboard')
    }

    const token = tokenFromUrl || localStorage.getItem('flowstate_token')
    if (!token) {
      navigate('/')
      return
    }

    fetch(`${API}/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(res => {
        if (!res.ok) throw new Error('Session expired')
        return res.json()
      })
      .then(setUser)
      .catch(err => {
        setError(err.message)
        localStorage.removeItem('flowstate_token')
        setTimeout(() => navigate('/'), 2000)
      })
  }, [navigate, searchParams])

  function handleLogout() {
    localStorage.removeItem('flowstate_token')
    navigate('/')
  }

  if (error) {
    return (
      <div style={styles.container}>
        <p style={{ color: '#ff6b6b' }}>{error} — redirecting...</p>
      </div>
    )
  }

  if (!user) {
    return (
      <div style={styles.container}>
        <div style={styles.loading}>🎵 Loading your profile...</div>
      </div>
    )
  }

  return (
    <div style={styles.container}>
      <div style={styles.card}>
        {/* Header */}
        <div style={styles.header}>
          <div>
            <h1 style={styles.title}>🎵 Flowstate</h1>
            <p style={styles.subtitle}>Welcome back, {user.display_name || 'Listener'}</p>
          </div>
          <button onClick={handleLogout} style={styles.logoutBtn}>
            Log out
          </button>
        </div>

        {/* User Info */}
        <div style={styles.profileCard}>
          <div style={styles.avatar}>
            {(user.display_name || 'U')[0].toUpperCase()}
          </div>
          <div>
            <p style={styles.name}>{user.display_name}</p>
            <p style={styles.email}>{user.email}</p>
            <p style={styles.spotifyId}>Spotify ID: {user.spotify_id}</p>
          </div>
        </div>

        {/* Coming Next */}
        <div style={styles.nextCard}>
          <h2 style={styles.nextTitle}>🚀 Phase 2 Coming Next</h2>
          <p style={styles.nextText}>
            Your Spotify library will be analyzed to extract audio features
            and classify each track's emotional signature.
          </p>
          <div style={styles.phases}>
            {[
              { icon: '✅', label: 'Phase 1: Spotify OAuth' },
              { icon: '⏳', label: 'Phase 2: Audio Feature Pipeline' },
              { icon: '⏳', label: 'Phase 3: Emotion Classifier' },
              { icon: '⏳', label: 'Phase 4: Arc Planning API' },
            ].map((p, i) => (
              <div key={i} style={styles.phase}>
                <span>{p.icon}</span>
                <span style={{ color: p.icon === '✅' ? '#1DB954' : '#a0a0c0' }}>
                  {p.label}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

const styles = {
  container: {
    minHeight: '100vh',
    background: 'linear-gradient(135deg, #0f0f1a 0%, #1a1a2e 50%, #0f0f1a 100%)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontFamily: "'Segoe UI', system-ui, sans-serif",
    padding: '20px',
  },
  loading: {
    color: '#a0a0c0',
    fontSize: '18px',
  },
  card: {
    background: 'rgba(255,255,255,0.05)',
    backdropFilter: 'blur(10px)',
    border: '1px solid rgba(255,255,255,0.1)',
    borderRadius: '24px',
    padding: '40px',
    maxWidth: '560px',
    width: '100%',
  },
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    marginBottom: '32px',
  },
  title: {
    fontSize: '24px',
    fontWeight: '700',
    color: '#ffffff',
    margin: '0 0 4px',
  },
  subtitle: {
    fontSize: '14px',
    color: '#a0a0c0',
    margin: 0,
  },
  logoutBtn: {
    background: 'transparent',
    border: '1px solid rgba(255,255,255,0.2)',
    color: '#a0a0c0',
    borderRadius: '20px',
    padding: '8px 16px',
    fontSize: '13px',
    cursor: 'pointer',
  },
  profileCard: {
    display: 'flex',
    alignItems: 'center',
    gap: '16px',
    background: 'rgba(29, 185, 84, 0.1)',
    border: '1px solid rgba(29, 185, 84, 0.3)',
    borderRadius: '16px',
    padding: '20px',
    marginBottom: '24px',
  },
  avatar: {
    width: '52px',
    height: '52px',
    borderRadius: '50%',
    background: '#1DB954',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontSize: '22px',
    fontWeight: '700',
    color: 'white',
    flexShrink: 0,
  },
  name: {
    color: '#ffffff',
    fontWeight: '600',
    fontSize: '16px',
    margin: '0 0 4px',
  },
  email: {
    color: '#a0a0c0',
    fontSize: '13px',
    margin: '0 0 2px',
  },
  spotifyId: {
    color: '#606080',
    fontSize: '12px',
    margin: 0,
  },
  nextCard: {
    background: 'rgba(255,255,255,0.03)',
    border: '1px solid rgba(255,255,255,0.08)',
    borderRadius: '16px',
    padding: '24px',
  },
  nextTitle: {
    color: '#ffffff',
    fontSize: '16px',
    fontWeight: '600',
    margin: '0 0 8px',
  },
  nextText: {
    color: '#a0a0c0',
    fontSize: '14px',
    lineHeight: '1.6',
    margin: '0 0 16px',
  },
  phases: {
    display: 'flex',
    flexDirection: 'column',
    gap: '8px',
  },
  phase: {
    display: 'flex',
    alignItems: 'center',
    gap: '10px',
    fontSize: '14px',
  },
}