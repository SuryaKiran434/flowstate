import React, { useEffect, useRef, useState } from 'react'

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1'

// ── Particle Constellation Canvas ────────────────────────────────────────────
function ConstellationBg() {
  const canvasRef = useRef(null)

  useEffect(() => {
    const canvas = canvasRef.current
    const ctx = canvas.getContext('2d')
    let animId
    let W, H, particles

    const PARTICLE_COUNT = 110
    const CONNECTION_DIST = 140
    const MOUSE = { x: -9999, y: -9999 }

    function resize() {
      W = canvas.width  = window.innerWidth
      H = canvas.height = window.innerHeight
    }

    function init() {
      resize()
      particles = Array.from({ length: PARTICLE_COUNT }, () => ({
        x:   Math.random() * W,
        y:   Math.random() * H,
        vx:  (Math.random() - 0.5) * 0.35,
        vy:  (Math.random() - 0.5) * 0.35,
        r:   Math.random() * 1.8 + 0.6,
        alpha: Math.random() * 0.5 + 0.3,
      }))
    }

    function draw() {
      ctx.clearRect(0, 0, W, H)

      // Move + bounce
      for (const p of particles) {
        p.x += p.vx; p.y += p.vy
        if (p.x < 0 || p.x > W) p.vx *= -1
        if (p.y < 0 || p.y > H) p.vy *= -1
      }

      // Connections
      for (let i = 0; i < particles.length; i++) {
        for (let j = i + 1; j < particles.length; j++) {
          const dx = particles[i].x - particles[j].x
          const dy = particles[i].y - particles[j].y
          const dist = Math.sqrt(dx*dx + dy*dy)
          if (dist < CONNECTION_DIST) {
            const opacity = (1 - dist / CONNECTION_DIST) * 0.25
            ctx.beginPath()
            ctx.strokeStyle = `rgba(139, 92, 246, ${opacity})`
            ctx.lineWidth = 0.6
            ctx.moveTo(particles[i].x, particles[i].y)
            ctx.lineTo(particles[j].x, particles[j].y)
            ctx.stroke()
          }
        }
        // Mouse connections
        const mx = particles[i].x - MOUSE.x
        const my = particles[i].y - MOUSE.y
        const md = Math.sqrt(mx*mx + my*my)
        if (md < 180) {
          const op = (1 - md / 180) * 0.5
          ctx.beginPath()
          ctx.strokeStyle = `rgba(99, 216, 255, ${op})`
          ctx.lineWidth = 0.8
          ctx.moveTo(particles[i].x, particles[i].y)
          ctx.lineTo(MOUSE.x, MOUSE.y)
          ctx.stroke()
        }
      }

      // Dots
      for (const p of particles) {
        ctx.beginPath()
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2)
        ctx.fillStyle = `rgba(180, 140, 255, ${p.alpha})`
        ctx.fill()
      }

      animId = requestAnimationFrame(draw)
    }

    const onMouse = e => { MOUSE.x = e.clientX; MOUSE.y = e.clientY }
    const onLeave = () => { MOUSE.x = -9999; MOUSE.y = -9999 }

    init()
    draw()
    window.addEventListener('resize', () => { resize(); init() })
    window.addEventListener('mousemove', onMouse)
    window.addEventListener('mouseleave', onLeave)

    return () => {
      cancelAnimationFrame(animId)
      window.removeEventListener('resize', init)
      window.removeEventListener('mousemove', onMouse)
      window.removeEventListener('mouseleave', onLeave)
    }
  }, [])

  return (
    <canvas ref={canvasRef} style={{
      position: 'fixed', inset: 0, zIndex: 0, pointerEvents: 'none'
    }} />
  )
}

// ── Home Page ─────────────────────────────────────────────────────────────────
export default function Home() {
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState(null)
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    // Check if already logged in
    const token = localStorage.getItem('flowstate_token')
    if (token) {
      window.location.href = '/dashboard'
      return
    }
    setTimeout(() => setVisible(true), 100)
  }, [])

  async function handleLogin() {
    setLoading(true)
    setError(null)
    try {
      const res  = await fetch(`${API}/auth/spotify/login`)
      const data = await res.json()
      window.location.href = data.auth_url
    } catch {
      setError('Failed to connect. Is the backend running?')
      setLoading(false)
    }
  }

  return (
    <div style={s.root}>
      <style>{css}</style>
      <ConstellationBg />

      <div style={{ ...s.card, opacity: visible ? 1 : 0, transform: visible ? 'translateY(0)' : 'translateY(24px)', transition: 'opacity 0.8s ease, transform 0.8s ease' }}>

        {/* Wordmark */}
        <div style={s.wordmark}>
          <span style={s.waveIcon}>◈</span>
          <span style={s.brand}>flowstate</span>
        </div>

        <h1 style={s.headline}>
          Music shaped<br />
          <span style={s.accent}>by how you feel.</span>
        </h1>

        <p style={s.sub}>
          Describe your mood. We'll build a playlist that takes you
          exactly where you want to be — one emotion at a time.
        </p>

        {/* Feature pills */}
        <div style={s.pills}>
          {['Emotion-aware arcs', 'Your library only', 'Mood to music in seconds'].map(t => (
            <span key={t} style={s.pill}>{t}</span>
          ))}
        </div>

        <button
          onClick={handleLogin}
          disabled={loading}
          className="spotify-btn"
          style={{ ...s.btn, opacity: loading ? 0.7 : 1 }}
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="white" style={{ flexShrink: 0 }}>
            <path d="M12 0C5.4 0 0 5.4 0 12s5.4 12 12 12 12-5.4 12-12S18.66 0 12 0zm5.521 17.34c-.24.359-.66.48-1.021.24-2.82-1.74-6.36-2.101-10.561-1.141-.418.122-.779-.179-.899-.539-.12-.421.18-.78.54-.9 4.56-1.021 8.52-.6 11.64 1.32.42.18.479.659.301 1.02zm1.44-3.3c-.301.42-.841.6-1.262.3-3.239-1.98-8.159-2.58-11.939-1.38-.479.12-1.02-.12-1.14-.6-.12-.48.12-1.021.6-1.141C9.6 9.9 15 10.561 18.72 12.84c.361.181.54.78.241 1.2zm.12-3.36C15.24 8.4 8.82 8.16 5.16 9.301c-.6.179-1.2-.181-1.38-.721-.18-.601.18-1.2.72-1.381 4.26-1.26 11.28-1.02 15.721 1.621.539.3.719 1.02.419 1.56-.299.421-1.02.599-1.559.3z"/>
          </svg>
          {loading ? 'Connecting...' : 'Continue with Spotify'}
        </button>

        {error && <p style={s.err}>{error}</p>}

        <p style={s.fine}>Your library stays yours. We never store listening history.</p>
      </div>
    </div>
  )
}

const css = `
  @import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=DM+Sans:ital,wght@0,300;0,400;1,300&display=swap');

  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #080612; }

  .spotify-btn:hover:not(:disabled) {
    background: #1ed760 !important;
    transform: translateY(-2px);
    box-shadow: 0 8px 32px rgba(29,185,84,0.4) !important;
  }
  .spotify-btn { transition: all 0.2s ease !important; }
`

const s = {
  root: {
    minHeight: '100vh',
    background: 'radial-gradient(ellipse at 20% 50%, #1a0533 0%, #080612 50%, #030310 100%)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontFamily: "'DM Sans', sans-serif",
    padding: '20px',
    position: 'relative',
    overflow: 'hidden',
  },
  card: {
    position: 'relative',
    zIndex: 1,
    maxWidth: '460px',
    width: '100%',
    textAlign: 'center',
    padding: '0 20px',
  },
  wordmark: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: '10px',
    marginBottom: '40px',
  },
  waveIcon: {
    fontSize: '22px',
    color: '#8b5cf6',
    animation: 'spin 8s linear infinite',
  },
  brand: {
    fontFamily: "'Syne', sans-serif",
    fontSize: '15px',
    fontWeight: '600',
    letterSpacing: '0.25em',
    textTransform: 'uppercase',
    color: 'rgba(255,255,255,0.5)',
  },
  headline: {
    fontFamily: "'Syne', sans-serif",
    fontSize: 'clamp(36px, 6vw, 56px)',
    fontWeight: '800',
    color: '#ffffff',
    lineHeight: 1.1,
    letterSpacing: '-1px',
    marginBottom: '24px',
  },
  accent: {
    background: 'linear-gradient(90deg, #8b5cf6, #63d8ff)',
    WebkitBackgroundClip: 'text',
    WebkitTextFillColor: 'transparent',
  },
  sub: {
    fontSize: '16px',
    color: 'rgba(255,255,255,0.5)',
    lineHeight: 1.7,
    marginBottom: '32px',
    fontWeight: '300',
  },
  pills: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: '8px',
    justifyContent: 'center',
    marginBottom: '40px',
  },
  pill: {
    fontSize: '12px',
    color: 'rgba(139,92,246,0.9)',
    border: '1px solid rgba(139,92,246,0.3)',
    borderRadius: '100px',
    padding: '5px 14px',
    background: 'rgba(139,92,246,0.08)',
    letterSpacing: '0.02em',
  },
  btn: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: '10px',
    width: '100%',
    padding: '15px 24px',
    background: '#1DB954',
    color: 'white',
    border: 'none',
    borderRadius: '100px',
    fontSize: '15px',
    fontWeight: '600',
    cursor: 'pointer',
    letterSpacing: '0.01em',
    boxShadow: '0 4px 20px rgba(29,185,84,0.25)',
  },
  err: {
    color: '#ff6b6b',
    fontSize: '13px',
    marginTop: '16px',
  },
  fine: {
    fontSize: '12px',
    color: 'rgba(255,255,255,0.2)',
    marginTop: '24px',
    lineHeight: 1.6,
  },
}
