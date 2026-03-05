import React, { useState } from 'react'

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1'

export default function Home() {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  async function handleLogin() {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`${API}/auth/spotify/login`)
      const data = await res.json()
      // Redirect user to Spotify authorization page
      window.location.href = data.auth_url
    } catch (err) {
      setError('Failed to connect to Flowstate API. Is the backend running?')
      setLoading(false)
    }
  }

  return (
    <div style={styles.container}>
      <div style={styles.card}>
        {/* Logo */}
        <div style={styles.logo}>🎵</div>

        {/* Title */}
        <h1 style={styles.title}>Flowstate</h1>
        <p style={styles.tagline}>Music that moves with you.</p>

        {/* Description */}
        <p style={styles.description}>
          Tell us where you are emotionally. We'll build a playlist
          that takes you where you want to be.
        </p>

        {/* Login Button */}
        <button
          onClick={handleLogin}
          disabled={loading}
          style={{
            ...styles.button,
            opacity: loading ? 0.7 : 1,
            cursor: loading ? 'not-allowed' : 'pointer',
          }}
        >
          {loading ? (
            'Connecting...'
          ) : (
            <>
              <span style={styles.spotifyIcon}>
                <svg width="20" height="20" viewBox="0 0 24 24" fill="white">
                  <path d="M12 0C5.4 0 0 5.4 0 12s5.4 12 12 12 12-5.4 12-12S18.66 0 12 0zm5.521 17.34c-.24.359-.66.48-1.021.24-2.82-1.74-6.36-2.101-10.561-1.141-.418.122-.779-.179-.899-.539-.12-.421.18-.78.54-.9 4.56-1.021 8.52-.6 11.64 1.32.42.18.479.659.301 1.02zm1.44-3.3c-.301.42-.841.6-1.262.3-3.239-1.98-8.159-2.58-11.939-1.38-.479.12-1.02-.12-1.14-.6-.12-.48.12-1.021.6-1.141C9.6 9.9 15 10.561 18.72 12.84c.361.181.54.78.241 1.2zm.12-3.36C15.24 8.4 8.82 8.16 5.16 9.301c-.6.179-1.2-.181-1.38-.721-.18-.601.18-1.2.72-1.381 4.26-1.26 11.28-1.02 15.721 1.621.539.3.719 1.02.419 1.56-.299.421-1.02.599-1.559.3z"/>
                </svg>
              </span>
              Continue with Spotify
            </>
          )}
        </button>

        {error && <p style={styles.error}>{error}</p>}

        <p style={styles.fine}>
          Flowstate uses your Spotify library to build personalized emotional arcs.
          We never store your listening history.
        </p>
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
  card: {
    background: 'rgba(255,255,255,0.05)',
    backdropFilter: 'blur(10px)',
    border: '1px solid rgba(255,255,255,0.1)',
    borderRadius: '24px',
    padding: '48px 40px',
    maxWidth: '420px',
    width: '100%',
    textAlign: 'center',
  },
  logo: {
    fontSize: '56px',
    marginBottom: '16px',
  },
  title: {
    fontSize: '36px',
    fontWeight: '700',
    color: '#ffffff',
    margin: '0 0 8px',
    letterSpacing: '-0.5px',
  },
  tagline: {
    fontSize: '16px',
    color: '#a0a0c0',
    margin: '0 0 24px',
    fontStyle: 'italic',
  },
  description: {
    fontSize: '15px',
    color: '#c0c0d8',
    lineHeight: '1.6',
    margin: '0 0 32px',
  },
  button: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: '10px',
    width: '100%',
    padding: '14px 24px',
    background: '#1DB954',
    color: 'white',
    border: 'none',
    borderRadius: '50px',
    fontSize: '16px',
    fontWeight: '600',
    transition: 'transform 0.1s, background 0.2s',
  },
  spotifyIcon: {
    display: 'flex',
    alignItems: 'center',
  },
  error: {
    color: '#ff6b6b',
    fontSize: '14px',
    marginTop: '16px',
  },
  fine: {
    fontSize: '12px',
    color: '#606080',
    marginTop: '24px',
    lineHeight: '1.5',
  },
}
