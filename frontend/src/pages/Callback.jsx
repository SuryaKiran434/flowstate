import React, { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1'

export default function Callback() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const [status, setStatus] = useState('Processing login...')

  useEffect(() => {
    const code  = searchParams.get('code')
    const state = searchParams.get('state')
    const error = searchParams.get('error')

    // Case 1: Spotify returned an error (user denied, etc.)
    if (error) {
      setStatus('Spotify login was cancelled or failed.')
      setTimeout(() => navigate('/'), 2000)
      return
    }

    // Case 2: Already have a JWT token (redirect from backend)
    const token = searchParams.get('token')
    if (token) {
      localStorage.setItem('flowstate_token', token)
      setStatus('Logged in! Redirecting...')
      setTimeout(() => navigate('/dashboard'), 500)
      return
    }

    // Case 3: Spotify redirected here with code + state
    // Forward to backend callback endpoint to exchange for tokens
    if (code && state) {
      setStatus('Completing login...')
      const backendCallback = `${API_URL}/auth/spotify/callback?code=${encodeURIComponent(code)}&state=${encodeURIComponent(state)}`
      // Backend will redirect back here with ?token= after exchange
      window.location.href = backendCallback
      return
    }

    // Case 4: Unexpected state
    setStatus('Something went wrong. Redirecting back...')
    setTimeout(() => navigate('/'), 2000)
  }, [searchParams, navigate])

  return (
    <div style={styles.container}>
      <div style={styles.card}>
        <div style={styles.spinner}>🎵</div>
        <p style={styles.text}>{status}</p>
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
  },
  card: {
    textAlign: 'center',
    padding: '48px',
  },
  spinner: {
    fontSize: '48px',
    marginBottom: '16px',
  },
  text: {
    color: '#a0a0c0',
    fontSize: '16px',
  },
}