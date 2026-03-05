import React, { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'

export default function Callback() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const [status, setStatus] = useState('Processing login...')

  useEffect(() => {
    const token = searchParams.get('token')
    const error = searchParams.get('error')

    if (error) {
      setStatus('Spotify login was cancelled or failed.')
      setTimeout(() => navigate('/'), 2000)
      return
    }

    if (token) {
      // Store JWT in localStorage
      localStorage.setItem('flowstate_token', token)
      setStatus('Logged in! Redirecting...')
      setTimeout(() => navigate('/dashboard'), 500)
      return
    }

    // No token and no error — unexpected state
    setStatus('Something went wrong. Redirecting...')
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
    animation: 'pulse 1s infinite',
    marginBottom: '16px',
  },
  text: {
    color: '#a0a0c0',
    fontSize: '16px',
  },
}
