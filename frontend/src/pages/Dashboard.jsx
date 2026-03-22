import React, { useEffect, useRef, useState, useCallback } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import SpotifyPlayer from '../components/SpotifyPlayer'
import ArcVisualizer from '../components/ArcVisualizer'

// ── Error boundary — shows crash details instead of blank page ────────────────
class ArcErrorBoundary extends React.Component {
  constructor(props) { super(props); this.state = { error: null } }
  static getDerivedStateFromError(error) { return { error } }
  render() {
    if (this.state.error) {
      return (
        <div style={{ padding: 40, color: '#f87171', fontFamily: 'monospace', fontSize: 13, background: '#0a0010', minHeight: '100vh' }}>
          <div style={{ color: '#f87171', fontWeight: 700, fontSize: 16, marginBottom: 16 }}>Arc render error</div>
          <pre style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-all', color: '#fca5a5' }}>{this.state.error.message}</pre>
          <pre style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-all', color: '#94a3b8', fontSize: 11, marginTop: 12 }}>{this.state.error.stack}</pre>
          <button onClick={() => { this.setState({ error: null }); this.props.onReset?.() }} style={{ marginTop: 24, padding: '8px 20px', background: '#7c3aed', color: '#fff', border: 'none', borderRadius: 8, cursor: 'pointer' }}>Back to input</button>
        </div>
      )
    }
    return this.props.children
  }
}

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1'

// ── Emotion color map ─────────────────────────────────────────────────────────
const EMOTION_COLORS = {
  energetic:   '#f59e0b', happy:      '#10b981', euphoric:  '#8b5cf6',
  peaceful:    '#06b6d4', focused:    '#3b82f6', romantic:  '#ec4899',
  nostalgic:   '#f97316', neutral:    '#6b7280', melancholic:'#6366f1',
  sad:         '#94a3b8', tense:      '#ef4444', angry:     '#dc2626',
}

const EMOTION_EMOJI = {
  energetic: '⚡', happy: '☀️', euphoric: '🌟', peaceful: '🌊',
  focused: '🎯', romantic: '💫', nostalgic: '🌙', neutral: '⚖️',
  melancholic: '🍂', sad: '🌧️', tense: '🌀', angry: '🔥',
}

// ── Constellation Background ──────────────────────────────────────────────────
// Module-level lerping accent color — updated by setConstellationColor()
const _cxColor = { r: 139, g: 92, b: 246 }
const _cxTarget = { r: 139, g: 92, b: 246 }

function _hexToRgb(hex) {
  const m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex)
  return m ? { r: parseInt(m[1], 16), g: parseInt(m[2], 16), b: parseInt(m[3], 16) } : null
}

export function setConstellationColor(hex) {
  const rgb = _hexToRgb(hex)
  if (rgb) { _cxTarget.r = rgb.r; _cxTarget.g = rgb.g; _cxTarget.b = rgb.b }
}

function ConstellationBg() {
  const canvasRef = useRef(null)
  useEffect(() => {
    const canvas = canvasRef.current
    const ctx = canvas.getContext('2d')
    let animId
    let W, H, particles
    const MOUSE = { x: -9999, y: -9999 }

    function resize() { W = canvas.width = window.innerWidth; H = canvas.height = window.innerHeight }
    function init() {
      resize()
      particles = Array.from({ length: 90 }, () => ({
        x: Math.random() * W, y: Math.random() * H,
        vx: (Math.random() - 0.5) * 0.25, vy: (Math.random() - 0.5) * 0.25,
        r: Math.random() * 1.5 + 0.5, alpha: Math.random() * 0.4 + 0.2,
      }))
    }
    function draw() {
      // Lerp accent color toward target (smooth ~3s transition)
      _cxColor.r += (_cxTarget.r - _cxColor.r) * 0.018
      _cxColor.g += (_cxTarget.g - _cxColor.g) * 0.018
      _cxColor.b += (_cxTarget.b - _cxColor.b) * 0.018
      const cr = Math.round(_cxColor.r), cg = Math.round(_cxColor.g), cb = Math.round(_cxColor.b)

      ctx.clearRect(0, 0, W, H)
      for (const p of particles) {
        p.x += p.vx; p.y += p.vy
        if (p.x < 0 || p.x > W) p.vx *= -1
        if (p.y < 0 || p.y > H) p.vy *= -1
      }
      for (let i = 0; i < particles.length; i++) {
        for (let j = i + 1; j < particles.length; j++) {
          const dx = particles[i].x - particles[j].x, dy = particles[i].y - particles[j].y
          const d = Math.sqrt(dx*dx + dy*dy)
          if (d < 120) {
            ctx.beginPath()
            ctx.strokeStyle = `rgba(${cr},${cg},${cb},${(1 - d/120) * 0.18})`
            ctx.lineWidth = 0.5
            ctx.moveTo(particles[i].x, particles[i].y)
            ctx.lineTo(particles[j].x, particles[j].y)
            ctx.stroke()
          }
        }
        const mx = particles[i].x - MOUSE.x, my = particles[i].y - MOUSE.y
        const md = Math.sqrt(mx*mx + my*my)
        if (md < 160) {
          ctx.beginPath()
          ctx.strokeStyle = `rgba(99,216,255,${(1-md/160)*0.4})`
          ctx.lineWidth = 0.7
          ctx.moveTo(particles[i].x, particles[i].y)
          ctx.lineTo(MOUSE.x, MOUSE.y)
          ctx.stroke()
        }
        ctx.beginPath()
        ctx.arc(particles[i].x, particles[i].y, particles[i].r, 0, Math.PI*2)
        ctx.fillStyle = `rgba(${Math.round(cr*1.1)},${cg},${Math.round(cb*1.05)},${particles[i].alpha})`
        ctx.fill()
      }
      animId = requestAnimationFrame(draw)
    }
    const onMouse = e => { MOUSE.x = e.clientX; MOUSE.y = e.clientY }
    const onLeave = () => { MOUSE.x = -9999; MOUSE.y = -9999 }
    init(); draw()
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
  return <canvas ref={canvasRef} style={{ position:'fixed', inset:0, zIndex:0, pointerEvents:'none' }} />
}

// ── Insights Panel ────────────────────────────────────────────────────────────
function InsightsPanel({ insights }) {
  const {
    streak_days, completion_rate, total_sessions, completed_sessions,
    top_starting_emotions, recent_arcs,
  } = insights

  return (
    <div style={{
      background: 'rgba(255,255,255,0.02)',
      border: '1px solid rgba(255,255,255,0.07)',
      borderRadius: 16,
      padding: '18px 20px',
      marginTop: 20,
    }}>
      <div style={s.sectionLabel}>Your listening patterns</div>

      {/* Summary stats row */}
      <div style={{ display: 'flex', gap: 10, marginBottom: 16, flexWrap: 'wrap' }}>
        {streak_days > 0 && (
          <div style={{
            display: 'flex', alignItems: 'center', gap: 6,
            background: 'rgba(139,92,246,0.1)', border: '1px solid rgba(139,92,246,0.25)',
            borderRadius: 8, padding: '6px 12px', fontSize: 12,
          }}>
            <span style={{ fontSize: 15 }}>🔥</span>
            <span style={{ color: '#c4b5fd', fontWeight: 600 }}>{streak_days}-day streak</span>
          </div>
        )}
        {total_sessions > 0 && (
          <div style={{
            display: 'flex', alignItems: 'center', gap: 6,
            background: 'rgba(6,182,212,0.08)', border: '1px solid rgba(6,182,212,0.2)',
            borderRadius: 8, padding: '6px 12px', fontSize: 12,
          }}>
            <span style={{ color: '#67e8f9', fontWeight: 600 }}>
              {Math.round(completion_rate * 100)}% completion
            </span>
            <span style={{ color: 'rgba(255,255,255,0.3)' }}>
              · {completed_sessions}/{total_sessions} sessions
            </span>
          </div>
        )}
      </div>

      {/* Top starting emotions */}
      {top_starting_emotions.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.3)', letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 8 }}>
            Most common starting emotions
          </div>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {top_starting_emotions.slice(0, 5).map(e => (
              <div key={e.emotion} style={{
                display: 'flex', alignItems: 'center', gap: 5,
                background: (EMOTION_COLORS[e.emotion] || '#8b5cf6') + '14',
                border: `1px solid ${(EMOTION_COLORS[e.emotion] || '#8b5cf6')}40`,
                borderRadius: 6, padding: '4px 10px', fontSize: 11,
              }}>
                <span>{EMOTION_EMOJI[e.emotion] || '◉'}</span>
                <span style={{ color: EMOTION_COLORS[e.emotion] || '#c4b5fd', fontWeight: 600 }}>
                  {e.emotion}
                </span>
                <span style={{ color: 'rgba(255,255,255,0.3)' }}>{e.pct}%</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Recent arcs timeline */}
      {recent_arcs.length > 0 && (
        <div>
          <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.3)', letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 8 }}>
            Recent arcs
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
            {recent_arcs.slice(0, 4).map(r => (
              <div key={r.session_id} style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                gap: 8, fontSize: 11, color: 'rgba(255,255,255,0.5)',
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
                  <span style={{
                    width: 6, height: 6, borderRadius: '50%', flexShrink: 0,
                    background: r.status === 'completed' ? '#10b981' : '#475569',
                  }} />
                  <span style={{ color: EMOTION_COLORS[r.source_emotion] || '#c4b5fd', fontWeight: 600 }}>
                    {r.source_emotion}
                  </span>
                  <span style={{ color: 'rgba(255,255,255,0.25)' }}>→</span>
                  <span style={{ color: EMOTION_COLORS[r.target_emotion] || '#c4b5fd', fontWeight: 600 }}>
                    {r.target_emotion}
                  </span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
                  {r.duration_mins && (
                    <span>{r.duration_mins} min</span>
                  )}
                  <span style={{ color: 'rgba(255,255,255,0.25)', fontSize: 10 }}>
                    {r.date}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Screen 1: Landing ─────────────────────────────────────────────────────────
function LandingScreen({ user, stats, readiness, modelStatus, insights, langStats, onStart, onDiscover, onCollab, onReclassify }) {
  const [reclassifying, setReclassifying] = useState(false)
  async function _reclassify() {
    setReclassifying(true)
    try { await onReclassify?.() } finally { setReclassifying(false) }
  }
  const [visible, setVisible] = useState(false)
  useEffect(() => { setTimeout(() => setVisible(true), 80) }, [])

  return (
    <div style={s.screen}>
      <div style={{ ...s.landingWrap, opacity: visible ? 1 : 0, transform: visible ? 'none' : 'translateY(20px)', transition: 'all 0.9s cubic-bezier(0.16,1,0.3,1)' }}>

        {/* Top nav */}
        <div style={s.nav}>
          <span style={s.navBrand}>◈ flowstate</span>
          <button onClick={() => { localStorage.removeItem('flowstate_token'); window.location.href = '/' }} style={s.logoutBtn}>
            Sign out
          </button>
        </div>

        {/* Hero */}
        <div style={s.hero}>
          <div style={s.greeting}>
            Good {getTimeOfDay()}, <span style={s.accentText}>{user?.display_name?.split(' ')[0] || 'Listener'}</span>
          </div>
          <h1 style={s.heroTitle}>What are you<br /><span style={s.heroAccent}>feeling right now?</span></h1>
          <p style={s.heroSub}>
            Your library. Your emotions. A playlist that moves with you.
          </p>
          <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap', justifyContent: 'center' }}>
            <button
              onClick={readiness && !readiness.ready_for_arc ? undefined : onStart}
              disabled={readiness != null && !readiness.ready_for_arc}
              className="start-btn"
              style={{ ...s.startBtn, opacity: readiness && !readiness.ready_for_arc ? 0.45 : 1, cursor: readiness && !readiness.ready_for_arc ? 'not-allowed' : 'pointer' }}
              title={readiness && !readiness.ready_for_arc ? readiness.message : undefined}
            >
              Build my arc
              <span style={s.arrow}>→</span>
            </button>
            <button
              onClick={onDiscover}
              className="start-btn"
              style={{
                ...s.startBtn,
                background: 'rgba(255,255,255,0.04)',
                border: '1px solid rgba(255,255,255,0.14)',
                color: 'rgba(255,255,255,0.7)',
                boxShadow: 'none',
              }}
            >
              Discover arcs
              <span style={s.arrow}>✦</span>
            </button>
            <button
              onClick={onCollab}
              className="start-btn"
              style={{
                ...s.startBtn,
                background: 'rgba(255,255,255,0.04)',
                border: '1px solid rgba(255,255,255,0.14)',
                color: 'rgba(255,255,255,0.7)',
                boxShadow: 'none',
              }}
            >
              Collaborate
              <span style={s.arrow}>⊕</span>
            </button>
          </div>
        </div>

        {/* Library readiness banner — shown when library is seeding or processing */}
        {readiness && readiness.state !== 'ready' && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', background: 'rgba(139,92,246,0.08)', border: '1px solid rgba(139,92,246,0.2)', borderRadius: '12px', padding: '10px 18px', marginBottom: '16px', fontSize: '13px', color: 'rgba(255,255,255,0.6)' }}>
            <span style={{ width: '7px', height: '7px', borderRadius: '50%', background: readiness.state === 'empty' ? '#8b5cf6' : '#06b6d4', boxShadow: `0 0 8px ${readiness.state === 'empty' ? '#8b5cf6' : '#06b6d4'}`, display: 'inline-block', flexShrink: 0 }} className="pulse-orb" />
            {readiness.message}
          </div>
        )}

        {/* Stats row */}
        {stats && (
          <div style={s.statsRow}>
            {[
              { label: 'Tracks', value: stats.total_tracks },
              { label: 'Analysed', value: stats.tracks_with_features },
              { label: 'Avg BPM', value: stats.avg_tempo_bpm },
              { label: 'Emotions', value: stats.tracks_with_emotions },
            ].map(({ label, value }) => (
              <div key={label} style={s.statCard}>
                <div style={s.statVal}>{value ?? '—'}</div>
                <div style={s.statLabel}>{label}</div>
              </div>
            ))}
          </div>
        )}

        {/* ML Classifier status */}
        {modelStatus && (
          <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            gap: 12, flexWrap: 'wrap',
            background: modelStatus.model_available
              ? 'rgba(16,185,129,0.06)' : 'rgba(255,255,255,0.03)',
            border: `1px solid ${modelStatus.model_available ? 'rgba(16,185,129,0.2)' : 'rgba(255,255,255,0.08)'}`,
            borderRadius: 12,
            padding: '10px 16px',
            marginBottom: 16,
            fontSize: 12,
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{
                width: 7, height: 7, borderRadius: '50%', flexShrink: 0, display: 'inline-block',
                background: modelStatus.model_available ? '#10b981' : '#475569',
                boxShadow: modelStatus.model_available ? '0 0 8px #10b981' : 'none',
              }} />
              <span style={{ color: modelStatus.model_available ? '#6ee7b7' : 'rgba(255,255,255,0.35)', fontWeight: 600 }}>
                ML Classifier
              </span>
              {modelStatus.model_available ? (
                <span style={{ color: 'rgba(255,255,255,0.4)' }}>
                  F1 {modelStatus.macro_f1?.toFixed(2)}
                  {' · '}{modelStatus.n_samples?.toLocaleString()} samples
                  {modelStatus.macro_f1 >= 0.75 ? ' · ✓ target met' : ''}
                </span>
              ) : (
                <span style={{ color: 'rgba(255,255,255,0.3)' }}>
                  No model trained — run <code style={{ fontSize: 11 }}>train_classifier.py</code>
                </span>
              )}
            </div>
            {modelStatus.can_reclassify && (
              <button
                onClick={_reclassify}
                disabled={reclassifying}
                style={{
                  background: 'rgba(16,185,129,0.12)',
                  border: '1px solid rgba(16,185,129,0.3)',
                  color: '#34d399',
                  borderRadius: 8,
                  padding: '5px 14px',
                  fontSize: 11,
                  cursor: reclassifying ? 'default' : 'pointer',
                  fontFamily: "'DM Sans', sans-serif",
                  whiteSpace: 'nowrap',
                }}
              >
                {reclassifying ? 'Reclassifying…' : 'Reclassify library'}
              </button>
            )}
          </div>
        )}

        {/* Emotion distribution */}
        {stats?.distribution && (
          <div style={s.emotionGrid}>
            <div style={s.sectionLabel}>Your emotional library</div>
            <div style={s.emotionPills}>
              {stats.distribution.slice(0, 8).map(e => (
                <div key={e.emotion_label} style={{ ...s.emotionPill, borderColor: EMOTION_COLORS[e.emotion_label] + '60', background: EMOTION_COLORS[e.emotion_label] + '18' }}>
                  <span>{EMOTION_EMOJI[e.emotion_label]}</span>
                  <span style={{ color: EMOTION_COLORS[e.emotion_label], fontWeight: 600, fontSize: '13px' }}>{e.emotion_label}</span>
                  <span style={{ color: 'rgba(255,255,255,0.4)', fontSize: '12px' }}>{e.percentage}%</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Language distribution — only shown when library is multilingual */}
        {langStats && langStats.multilingual && (
          <div style={{ marginTop: 20 }}>
            <div style={s.sectionLabel}>
              Languages · {langStats.language_count} detected · classifier is language-agnostic
            </div>
            <div style={s.emotionPills}>
              {langStats.distribution.slice(0, 8).map(l => (
                <div key={l.language} style={{ ...s.emotionPill, borderColor: 'rgba(139,92,246,0.35)', background: 'rgba(139,92,246,0.08)' }}>
                  <span>{l.flag}</span>
                  <span style={{ color: 'rgba(255,255,255,0.75)', fontWeight: 600, fontSize: '13px' }}>{l.name}</span>
                  <span style={{ color: 'rgba(255,255,255,0.35)', fontSize: '12px' }}>{l.percentage}%</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Insights panel — only shown when user has sessions */}
        {insights && insights.total_sessions > 0 && (
          <InsightsPanel insights={insights} />
        )}
      </div>
    </div>
  )
}

// ── Screen 2: Mood Input ──────────────────────────────────────────────────────
function MoodInputScreen({ onSubmit, onBack, authToken }) {
  const [text, setText]             = useState('')
  const [duration, setDuration]     = useState(30)
  const [focused, setFocused]       = useState(false)
  const [visible, setVisible]       = useState(false)
  const [suggestion, setSuggestion] = useState(null)  // context-aware arc suggestion
  const [langFilter, setLangFilter] = useState([])    // language filter (empty = all)
  const [langStats, setLangStats]   = useState(null)
  const textareaRef                 = useRef(null)

  useEffect(() => {
    setTimeout(() => { setVisible(true); setTimeout(() => textareaRef.current?.focus(), 400) }, 80)
  }, [])

  // Fetch context-aware suggestion + language stats on mount (non-blocking)
  useEffect(() => {
    if (!authToken) return
    const hdrs = { Authorization: `Bearer ${authToken}` }
    fetch(`${API}/arc/suggest`, { headers: hdrs })
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d?.source && d?.target) setSuggestion(d) })
      .catch(() => {})
    fetch(`${API}/tracks/language-stats`, { headers: hdrs })
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d?.multilingual) setLangStats(d) })
      .catch(() => {})
  }, [authToken])

  const hints = [
    "I'm anxious about tomorrow, want to feel calm",
    "Just finished a workout, need to wind down",
    "Feeling nostalgic and want to stay in that mood",
    "Low energy Monday, need motivation",
    "Heartbroken, just want to feel something",
  ]

  return (
    <div style={s.screen}>
      <div style={{ ...s.inputWrap, opacity: visible ? 1 : 0, transform: visible ? 'none' : 'translateY(20px)', transition: 'all 0.7s cubic-bezier(0.16,1,0.3,1)' }}>

        <button onClick={onBack} style={s.backBtn}>← back</button>

        {/* Context-aware suggestion card */}
        {suggestion && (
          <div style={{
            background: 'rgba(139, 92, 246, 0.08)',
            border: '1px solid rgba(139, 92, 246, 0.25)',
            borderRadius: 14,
            padding: '14px 18px',
            marginBottom: 24,
            display: 'flex',
            alignItems: 'flex-start',
            gap: 14,
          }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ color: '#94a3b8', fontSize: 11, letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 6 }}>
                Suggested for you
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6, flexWrap: 'wrap' }}>
                <span style={{ color: EMOTION_COLORS[suggestion.source] || '#a78bfa', fontWeight: 600, fontSize: 14 }}>
                  {EMOTION_EMOJI[suggestion.source]} {suggestion.source}
                </span>
                <span style={{ color: 'rgba(255,255,255,0.3)', fontSize: 13 }}>→</span>
                <span style={{ color: EMOTION_COLORS[suggestion.target] || '#a78bfa', fontWeight: 600, fontSize: 14 }}>
                  {EMOTION_EMOJI[suggestion.target]} {suggestion.target}
                </span>
              </div>
              <div style={{ color: 'rgba(255,255,255,0.5)', fontSize: 12, lineHeight: 1.5 }}>
                {suggestion.interpretation}
              </div>
              {suggestion.context_signals?.length > 0 && (
                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 8 }}>
                  {suggestion.context_signals.slice(0, 3).map(sig => (
                    <span key={sig} style={{
                      background: 'rgba(139, 92, 246, 0.12)',
                      border: '1px solid rgba(139, 92, 246, 0.2)',
                      borderRadius: 100,
                      padding: '2px 10px',
                      color: '#94a3b8',
                      fontSize: 11,
                    }}>
                      {sig}
                    </span>
                  ))}
                </div>
              )}
            </div>
            <button
              onClick={() => onSubmit(suggestion.interpretation, duration, suggestion.source, suggestion.target, langFilter.length ? langFilter : null)}
              style={{
                background: 'rgba(139, 92, 246, 0.2)',
                border: '1px solid rgba(139, 92, 246, 0.4)',
                borderRadius: 8,
                color: '#c4b5fd',
                fontSize: 12,
                fontWeight: 600,
                padding: '8px 14px',
                cursor: 'pointer',
                whiteSpace: 'nowrap',
                fontFamily: "'DM Sans', sans-serif",
                flexShrink: 0,
              }}
            >
              Use this
            </button>
          </div>
        )}

        <div style={s.inputHeader}>
          <div style={s.inputLabel}>How are you feeling?</div>
          <p style={s.inputSub}>Describe your mood in your own words — we'll handle the rest.</p>
        </div>

        {/* Main input */}
        <div style={{ ...s.textareaWrap, boxShadow: focused ? '0 0 0 2px rgba(139,92,246,0.5), 0 20px 60px rgba(139,92,246,0.15)' : '0 8px 32px rgba(0,0,0,0.4)' }}>
          <textarea
            ref={textareaRef}
            value={text}
            onChange={e => setText(e.target.value)}
            onFocus={() => setFocused(true)}
            onBlur={() => setFocused(false)}
            placeholder="e.g. I'm stressed from work and want to relax..."
            style={s.textarea}
            rows={4}
            maxLength={400}
          />
          <div style={s.charCount}>{text.length}/400</div>
        </div>

        {/* Hint chips */}
        <div style={s.hintsWrap}>
          <div style={s.hintsLabel}>Try one of these</div>
          <div style={s.hints}>
            {hints.map(h => (
              <button key={h} onClick={() => setText(h)} className="hint-chip" style={s.hintChip}>
                {h}
              </button>
            ))}
          </div>
        </div>

        {/* Duration */}
        <div style={s.durationWrap}>
          <div style={s.durationLabel}>
            Session length <span style={{ color: '#8b5cf6', fontWeight: 700 }}>{duration} min</span>
          </div>
          <input
            type="range" min={10} max={90} step={5} value={duration}
            onChange={e => setDuration(Number(e.target.value))}
            style={s.slider}
            className="mood-slider"
          />
          <div style={s.sliderMarks}>
            {[10, 30, 60, 90].map(v => <span key={v} style={{ ...s.sliderMark, opacity: duration === v ? 1 : 0.4 }}>{v}m</span>)}
          </div>
        </div>

        {/* Language filter — only shown for multilingual libraries */}
        {langStats && (
          <div style={{ marginBottom: 28 }}>
            <div style={{ fontSize: 12, color: 'rgba(255,255,255,0.35)', letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 10 }}>
              Language filter · classifier is language-agnostic
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              {langStats.distribution.map(l => {
                const active = langFilter.includes(l.language)
                return (
                  <button key={l.language} onClick={() => {
                    setLangFilter(prev =>
                      prev.includes(l.language)
                        ? prev.filter(x => x !== l.language)
                        : [...prev, l.language]
                    )
                  }} style={{
                    background: active ? 'rgba(139,92,246,0.2)' : 'rgba(255,255,255,0.04)',
                    border: `1px solid ${active ? 'rgba(139,92,246,0.5)' : 'rgba(255,255,255,0.1)'}`,
                    color: active ? '#c4b5fd' : 'rgba(255,255,255,0.45)',
                    borderRadius: 100, padding: '5px 14px', fontSize: 12, fontWeight: 600,
                    cursor: 'pointer', fontFamily: "'DM Sans', sans-serif",
                  }}>
                    {l.flag} {l.name} <span style={{ opacity: 0.6, marginLeft: 2 }}>{l.percentage}%</span>
                  </button>
                )
              })}
            </div>
            {langFilter.length > 0 && (
              <div style={{ marginTop: 8, fontSize: 11, color: 'rgba(139,92,246,0.7)' }}>
                Filtering to {langFilter.length} language{langFilter.length > 1 ? 's' : ''} · {langStats.distribution.filter(l => langFilter.includes(l.language)).reduce((s, l) => s + l.count, 0)} tracks
              </div>
            )}
          </div>
        )}

        <button
          onClick={() => text.trim().length > 3 && onSubmit(text, duration, null, null, langFilter.length ? langFilter : null)}
          disabled={text.trim().length < 4}
          className="generate-btn"
          style={{ ...s.generateBtn, opacity: text.trim().length < 4 ? 0.4 : 1, cursor: text.trim().length < 4 ? 'not-allowed' : 'pointer' }}
        >
          Generate my arc
        </button>
      </div>
    </div>
  )
}

// ── Screen 3: Loading (Free Music) ────────────────────────────────────────────
function LoadingScreen({ moodText, waitTrack }) {
  const [dots, setDots] = useState('.')
  const [step, setStep] = useState(0)
  const steps = ['Reading your mood...', 'Mapping emotions...', 'Curating your arc...', 'Sequencing tracks...']

  useEffect(() => {
    const di = setInterval(() => setDots(d => d.length >= 3 ? '.' : d + '.'), 500)
    const si = setInterval(() => setStep(s => Math.min(s + 1, steps.length - 1)), 1800)
    return () => { clearInterval(di); clearInterval(si) }
  }, [])

  return (
    <div style={s.screen}>
      <div style={s.loadingWrap}>
        <div style={s.loadingTop}>
          <div style={s.loadingOrb} className="pulse-orb" />
          <div style={s.loadingStatus}>{steps[step]}{dots}</div>
          <div style={s.loadingMood}>"{moodText}"</div>
        </div>

        {waitTrack && (
          <div style={s.waitMusicWrap}>
            <div style={s.waitMusicLabel}>While we craft your arc — enjoy a moment</div>
            <div style={s.spotifyEmbed}>
              <iframe
                src={`https://open.spotify.com/embed/track/${waitTrack}?utm_source=generator&theme=0`}
                width="100%"
                height="152"
                frameBorder="0"
                allow="autoplay; clipboard-write; encrypted-media; fullscreen; picture-in-picture"
                loading="lazy"
                style={{ borderRadius: '12px' }}
              />
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Screen 4: Arc Result ──────────────────────────────────────────────────────
function ArcResultScreen({ arc: initialArc, onReset, spotifyToken, sessionId, authToken }) {
  const [arc, setArc]                 = useState(initialArc)  // may be replaced by replan
  const [visible, setVisible]         = useState(false)
  const [expanded, setExpanded]       = useState(null)
  const [playingIndex, setPlayingIndex] = useState(null)
  const [replanNotice, setReplanNotice] = useState(null)  // string | null
  const [replanning, setReplanning]   = useState(false)
  const playerRef                     = useRef(null)
  const sessionStatus                 = useRef('generated') // track without re-render
  const quickSkipCountRef             = useRef(0)
  useEffect(() => { setTimeout(() => setVisible(true), 80) }, [])

  // ── Session telemetry helpers ──────────────────────────────────────────────
  const patchSession = useCallback((status) => {
    if (!sessionId || !authToken) return
    const current = sessionStatus.current
    const allowed = { generated: ['active'], active: ['completed', 'abandoned'] }
    if (!allowed[current]?.includes(status)) return
    sessionStatus.current = status
    fetch(`${API}/sessions/${sessionId}`, {
      method: 'PATCH',
      headers: { Authorization: `Bearer ${authToken}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ status }),
    }).catch(() => {})
  }, [sessionId, authToken])

  const postTrackEvent = useCallback((position, event) => {
    if (!sessionId || !authToken) return
    fetch(`${API}/sessions/${sessionId}/events`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${authToken}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ position, event }),
    }).catch(() => {})
  }, [sessionId, authToken])

  // Abandon session if user navigates away without completing
  useEffect(() => {
    return () => { patchSession('abandoned') }
  }, [patchSession])

  // ── Skip-driven re-planning ────────────────────────────────────────────────
  const handleReplan = useCallback(async (currentPosition) => {
    if (!sessionId || !authToken || replanning) return
    setReplanning(true)

    // Remaining duration: sum of tracks from currentPosition onward (in minutes)
    const remainingMs = (arc.tracks || [])
      .slice(currentPosition)
      .reduce((sum, t) => sum + (t.duration_ms || 0), 0)
    const remainingMins = Math.max(5, Math.round(remainingMs / 60000))

    try {
      const res = await fetch(`${API}/arc/replan`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${authToken}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId,
          current_position: currentPosition,
          remaining_duration_minutes: remainingMins,
        }),
      })
      if (!res.ok) return
      const newArc = await res.json()

      setArc(prev => ({
        ...prev,
        arc_path:          newArc.arc_path,
        segments:          newArc.segments,
        tracks:            newArc.tracks,
        total_tracks:      newArc.total_tracks,
        total_duration_ms: newArc.total_duration_ms,
      }))
      setExpanded(null)
      setPlayingIndex(null)
      setReplanNotice(newArc.replan_reason || 'Arc re-routed')
      setTimeout(() => setReplanNotice(null), 4000)
    } catch {
      // non-fatal — continue with existing arc
    } finally {
      setReplanning(false)
      quickSkipCountRef.current = 0
    }
  }, [sessionId, authToken, arc, replanning])

  const handleQuickSkip = useCallback((skippedIndex) => {
    postTrackEvent(skippedIndex, 'skip')
    quickSkipCountRef.current += 1
    if (quickSkipCountRef.current >= 2) {
      handleReplan(skippedIndex + 1)
    }
  }, [postTrackEvent, handleReplan])

  const totalMin = Math.round((arc.total_duration_ms || 0) / 60000)

  // Build a map from (segmentIndex, trackIndex) → flat arc.tracks index
  // so clicking a segment track can address the global flat list
  const segTrackOffset = (arc.segments || []).reduce((acc, seg, si) => {
    acc[si] = si === 0 ? 0 : acc[si - 1] + (arc.segments[si - 1]?.track_count || 0)
    return acc
  }, {})

  const handleTrackClick = (segIndex, trackIndex) => {
    const globalIndex = (segTrackOffset[segIndex] || 0) + trackIndex
    patchSession('active')
    setPlayingIndex(globalIndex)
    playerRef.current?.playFromIndex(globalIndex)
    setExpanded(segIndex)
  }

  const handleTrackChange = useCallback((newIndex) => {
    patchSession('active')
    postTrackEvent(newIndex, 'play')
    setPlayingIndex(newIndex)
  }, [patchSession, postTrackEvent])

  // ── Mid-session natural language adjust ───────────────────────────────────
  const [commandOpen, setCommandOpen]   = useState(false)
  const [commandText, setCommandText]   = useState('')
  const [adjusting, setAdjusting]       = useState(false)
  const commandInputRef                 = useRef(null)

  // ── Share arc as template ─────────────────────────────────────────────────
  const [sharing, setSharing]           = useState(false)
  const [shareSuccess, setShareSuccess] = useState(false)

  const handleShare = useCallback(async () => {
    if (sharing || !authToken) return
    setSharing(true)
    try {
      const res = await fetch(`${API}/templates`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${authToken}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({
          display_name:   arc.mood_interpretation || `${arc.source_emotion} → ${arc.target_emotion}`,
          description:    arc.mood_interpretation,
          source_emotion: arc.source_emotion,
          target_emotion: arc.target_emotion,
          arc_path:       arc.arc_path,
          duration_mins:  Math.max(5, Math.round(arc.total_duration_ms / 60000)),
        }),
      })
      if (res.ok) {
        setShareSuccess(true)
        setTimeout(() => setShareSuccess(false), 3000)
      }
    } catch {
      // non-fatal
    } finally {
      setSharing(false)
    }
  }, [sharing, authToken, arc])

  useEffect(() => {
    if (commandOpen) commandInputRef.current?.focus()
  }, [commandOpen])

  const handleAdjust = useCallback(async () => {
    if (!commandText.trim() || !sessionId || !authToken || adjusting) return
    setAdjusting(true)

    const position = playingIndex ?? 0
    const remainingMs = (arc.tracks || []).slice(position).reduce((s, t) => s + (t.duration_ms || 0), 0)
    const remainingMins = Math.max(5, Math.round(remainingMs / 60000))

    try {
      const res = await fetch(`${API}/arc/adjust`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${authToken}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id:                 sessionId,
          current_position:           position,
          command:                    commandText.trim(),
          remaining_duration_minutes: remainingMins,
        }),
      })
      if (!res.ok) return
      const newArc = await res.json()

      setArc(prev => ({
        ...prev,
        arc_path:          newArc.arc_path,
        segments:          newArc.segments,
        tracks:            newArc.tracks,
        total_tracks:      newArc.total_tracks,
        total_duration_ms: newArc.total_duration_ms,
      }))
      setExpanded(null)
      setPlayingIndex(null)
      setReplanNotice(newArc.command_interpretation || 'Arc adjusted')
      setTimeout(() => setReplanNotice(null), 5000)
      setCommandText('')
      setCommandOpen(false)
    } catch {
      // non-fatal
    } finally {
      setAdjusting(false)
    }
  }, [commandText, sessionId, authToken, adjusting, playingIndex, arc])

  // ── Audio-visual emotion sync ─────────────────────────────────────────────
  useEffect(() => {
    const emotion = playingIndex != null ? arc.tracks[playingIndex]?.emotion_label : null
    const hex = (emotion && EMOTION_COLORS[emotion]) ? EMOTION_COLORS[emotion] : '#8b5cf6'
    document.documentElement.style.setProperty('--emotion-primary', hex)
    setConstellationColor(hex)
    return () => { document.documentElement.style.removeProperty('--emotion-primary') }
  }, [playingIndex, arc.tracks])

  return (
    <div style={{ ...s.screen, alignItems: 'flex-start', overflowY: 'auto', paddingBottom: spotifyToken ? 90 : 0 }}>
      {/* Emotion aura — full-page tint that transitions with current emotion */}
      {playingIndex != null && (
        <div style={{
          position: 'fixed', inset: 0, zIndex: 0, pointerEvents: 'none',
          background: `radial-gradient(ellipse at 50% 80%, var(--emotion-primary, #8b5cf6) 0%, transparent 65%)`,
          opacity: 0.07,
          transition: 'background 1.4s ease',
        }} />
      )}
      <div style={{ ...s.arcWrap, opacity: visible ? 1 : 0, transition: 'opacity 0.6s ease' }}>

        {/* Header */}
        <div style={s.arcHeader}>
          <div>
            <div style={s.arcInterpret}>{arc.mood_interpretation}</div>
            <div style={s.arcMeta}>
              {arc.total_tracks} tracks · {totalMin} min · {(arc.arc_path || []).length} emotional stages
              {arc.personalised && (
                <span style={{
                  marginLeft: 10,
                  background: 'rgba(139, 92, 246, 0.15)',
                  border: '1px solid rgba(139, 92, 246, 0.35)',
                  borderRadius: 100,
                  padding: '1px 9px',
                  fontSize: 11,
                  color: '#a78bfa',
                  verticalAlign: 'middle',
                }}>
                  personalised
                </span>
              )}
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <button
              onClick={handleShare}
              disabled={sharing || shareSuccess}
              title="Share this arc as a template others can remix"
              style={{
                background: shareSuccess ? 'rgba(16,185,129,0.15)' : 'rgba(255,255,255,0.05)',
                border: `1px solid ${shareSuccess ? 'rgba(16,185,129,0.4)' : 'rgba(255,255,255,0.12)'}`,
                color: shareSuccess ? '#34d399' : 'rgba(255,255,255,0.6)',
                borderRadius: 8,
                padding: '6px 14px',
                fontSize: 12,
                cursor: sharing || shareSuccess ? 'default' : 'pointer',
                fontFamily: "'DM Sans', sans-serif",
                transition: 'all 0.2s',
              }}
            >
              {shareSuccess ? '✓ Shared' : sharing ? '…' : '↑ Share'}
            </button>
            <button onClick={() => { patchSession('abandoned'); onReset() }} style={s.newArcBtn}>New arc</button>
          </div>
        </div>

        {/* Replan toast */}
        {replanNotice && (
          <div style={{
            background: 'rgba(139, 92, 246, 0.15)',
            border: '1px solid rgba(139, 92, 246, 0.4)',
            borderRadius: 10,
            padding: '10px 16px',
            color: '#c4b5fd',
            fontSize: 13,
            marginBottom: 8,
            display: 'flex',
            alignItems: 'center',
            gap: 8,
          }}>
            <span>↺</span>
            <span>{replanNotice}</span>
          </div>
        )}
        {replanning && (
          <div style={{
            background: 'rgba(139, 92, 246, 0.08)',
            border: '1px solid rgba(139, 92, 246, 0.2)',
            borderRadius: 10,
            padding: '10px 16px',
            color: '#94a3b8',
            fontSize: 13,
            marginBottom: 8,
          }}>
            Re-routing arc…
          </div>
        )}

        {/* Path visualization */}
        <div style={s.pathWrap}>
          {(arc.arc_path || []).map((emotion, i) => (
            <React.Fragment key={emotion}>
              <div style={s.pathNode}>
                <div style={{ ...s.pathBubble, background: EMOTION_COLORS[emotion] + '22', border: `1.5px solid ${EMOTION_COLORS[emotion]}`, boxShadow: `0 0 20px ${EMOTION_COLORS[emotion]}33` }}>
                  <span style={{ fontSize: '18px' }}>{EMOTION_EMOJI[emotion]}</span>
                </div>
                <span style={{ ...s.pathLabel, color: EMOTION_COLORS[emotion] }}>{emotion}</span>
              </div>
              {i < arc.arc_path.length - 1 && (
                <div style={s.pathArrow}>
                  <div style={{ ...s.pathLine, background: `linear-gradient(90deg, ${EMOTION_COLORS[emotion]}, ${EMOTION_COLORS[arc.arc_path[i+1]]})` }} />
                  <span style={s.pathChevron}>›</span>
                </div>
              )}
            </React.Fragment>
          ))}
        </div>

        {/* Energy + valence arc chart */}
        <ArcVisualizer
          tracks={arc.tracks}
          segments={arc.segments}
          arcPath={arc.arc_path}
          playingIndex={playingIndex}
          onTrackClick={spotifyToken ? (idx) => {
            setPlayingIndex(idx)
            playerRef.current?.playFromIndex(idx)
          } : undefined}
        />

        {/* Segments */}
        <div style={s.segmentsWrap}>
          {(arc.segments || []).map((seg, si) => (
            <div key={seg.emotion} style={s.segment}>
              <div style={s.segHeader} onClick={() => setExpanded(expanded === si ? null : si)}>
                <div style={s.segLeft}>
                  <div style={{ ...s.segDot, background: EMOTION_COLORS[seg.emotion] }} />
                  <span style={s.segEmotion}>{EMOTION_EMOJI[seg.emotion]} {seg.emotion}</span>
                  <span style={s.segCount}>{seg.track_count} tracks</span>
                  <span style={{ ...s.segDir, color: seg.energy_direction === 'descending' ? '#06b6d4' : seg.energy_direction === 'ascending' ? '#f59e0b' : '#6b7280' }}>
                    {seg.energy_direction === 'descending' ? '↓ winding down' : seg.energy_direction === 'ascending' ? '↑ building up' : '→ steady'}
                  </span>
                </div>
                <span style={{ color: 'rgba(255,255,255,0.3)', fontSize: '18px' }}>{expanded === si ? '−' : '+'}</span>
              </div>

              {expanded === si && (
                <div style={s.trackList}>
                  {seg.tracks.map((track, ti) => {
                    const globalIdx = (segTrackOffset[si] || 0) + ti
                    const isPlaying = playingIndex === globalIdx
                    return (
                      <div
                        key={track.spotify_id}
                        style={{
                          ...s.trackRow,
                          cursor: spotifyToken ? 'pointer' : 'default',
                          background: isPlaying
                            ? `${EMOTION_COLORS[track.emotion_label]}18`
                            : 'transparent',
                          borderLeft: isPlaying
                            ? `3px solid ${EMOTION_COLORS[track.emotion_label]}`
                            : '3px solid transparent',
                          paddingLeft: isPlaying ? 9 : 12,
                          transition: 'background 0.2s, border-color 0.2s',
                        }}
                        className={`track-row${isPlaying ? ' playing-track-row' : ''}`}
                        onClick={() => spotifyToken && handleTrackClick(si, ti)}
                      >
                        <div style={{ ...s.trackNum, color: isPlaying ? EMOTION_COLORS[track.emotion_label] : s.trackNum.color }}>
                          {isPlaying ? '▶' : ti + 1}
                        </div>
                        <div style={s.trackInfo}>
                          <div style={{ ...s.trackTitle, color: isPlaying ? EMOTION_COLORS[track.emotion_label] : s.trackTitle.color }}>{track.title}</div>
                          <div style={s.trackArtist}>{track.artist}</div>
                        </div>
                        <div style={s.trackMeta}>
                          {track.language && track.language !== 'en' && (
                            <span style={{
                              fontSize: 10, color: 'rgba(255,255,255,0.35)',
                              background: 'rgba(255,255,255,0.06)',
                              border: '1px solid rgba(255,255,255,0.1)',
                              borderRadius: 4, padding: '1px 6px',
                              letterSpacing: '0.05em', flexShrink: 0,
                            }}>
                              {track.language.toUpperCase()}
                            </span>
                          )}
                          <div style={s.energyBar}>
                            <div style={{ ...s.energyFill, width: `${track.energy * 100}%`, background: EMOTION_COLORS[track.emotion_label] }} />
                          </div>
                          <span style={s.trackDur}>{Math.round(track.duration_ms / 60000)}:{String(Math.round((track.duration_ms % 60000) / 1000)).padStart(2,'0')}</span>
                        </div>
                        <a href={`https://open.spotify.com/track/${track.spotify_id}`} target="_blank" rel="noreferrer" style={s.spotifyLink} onClick={e => e.stopPropagation()}>
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M12 0C5.4 0 0 5.4 0 12s5.4 12 12 12 12-5.4 12-12S18.66 0 12 0zm5.521 17.34c-.24.359-.66.48-1.021.24-2.82-1.74-6.36-2.101-10.561-1.141-.418.122-.779-.179-.899-.539-.12-.421.18-.78.54-.9 4.56-1.021 8.52-.6 11.64 1.32.42.18.479.659.301 1.02zm1.44-3.3c-.301.42-.841.6-1.262.3-3.239-1.98-8.159-2.58-11.939-1.38-.479.12-1.02-.12-1.14-.6-.12-.48.12-1.021.6-1.141C9.6 9.9 15 10.561 18.72 12.84c.361.181.54.78.241 1.2zm.12-3.36C15.24 8.4 8.82 8.16 5.16 9.301c-.6.179-1.2-.181-1.38-.721-.18-.601.18-1.2.72-1.381 4.26-1.26 11.28-1.02 15.721 1.621.539.3.719 1.02.419 1.56-.299.421-1.02.599-1.559.3z"/></svg>
                        </a>
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          ))}
        </div>

        {arc.warnings?.length > 0 && (
          <div style={s.warning}>⚠ {arc.warnings[0]}</div>
        )}
      </div>

      {/* Mid-session command bar — floats above the player when playing */}
      {spotifyToken && playingIndex !== null && (
        <div style={{
          position: 'fixed',
          bottom: commandOpen ? 86 : 76,
          right: 24,
          zIndex: 1001,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'flex-end',
          gap: 8,
          transition: 'bottom 0.2s ease',
        }}>
          {commandOpen && (
            <div style={{
              display: 'flex',
              gap: 8,
              alignItems: 'center',
              background: 'rgba(10, 6, 20, 0.97)',
              border: '1px solid rgba(139, 92, 246, 0.4)',
              borderRadius: 12,
              padding: '8px 12px',
              backdropFilter: 'blur(20px)',
              boxShadow: '0 4px 24px rgba(0,0,0,0.4)',
              width: 340,
            }}>
              <input
                ref={commandInputRef}
                value={commandText}
                onChange={e => setCommandText(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') handleAdjust(); if (e.key === 'Escape') setCommandOpen(false) }}
                placeholder="Adjust arc... e.g. 'slow this down'"
                style={{
                  flex: 1,
                  background: 'none',
                  border: 'none',
                  outline: 'none',
                  color: '#e2e8f0',
                  fontSize: 13,
                  fontFamily: "'DM Sans', sans-serif",
                }}
                disabled={adjusting}
              />
              <button
                onClick={handleAdjust}
                disabled={adjusting || !commandText.trim()}
                style={{
                  background: 'none',
                  border: 'none',
                  cursor: adjusting || !commandText.trim() ? 'default' : 'pointer',
                  color: adjusting || !commandText.trim() ? '#475569' : '#a78bfa',
                  fontSize: 16,
                  padding: 0,
                  lineHeight: 1,
                }}
              >
                {adjusting ? '…' : '↵'}
              </button>
            </div>
          )}
          <button
            onClick={() => setCommandOpen(o => !o)}
            title="Adjust arc with natural language"
            style={{
              background: commandOpen
                ? 'rgba(139, 92, 246, 0.25)'
                : 'rgba(10, 6, 20, 0.9)',
              border: '1px solid rgba(139, 92, 246, 0.4)',
              borderRadius: '50%',
              width: 36,
              height: 36,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              cursor: 'pointer',
              color: '#a78bfa',
              fontSize: 16,
              backdropFilter: 'blur(12px)',
              transition: 'background 0.2s',
            }}
          >
            ✦
          </button>
        </div>
      )}

      {spotifyToken && (
        <SpotifyPlayer
          ref={playerRef}
          tracks={arc.tracks || []}
          spotifyToken={spotifyToken}
          onTrackChange={handleTrackChange}
          onQuickSkip={handleQuickSkip}
        />
      )}
    </div>
  )
}

// ── Screen 5: Discover Templates ─────────────────────────────────────────────
function DiscoverScreen({ onBack, authToken, onRemix }) {
  const [templates, setTemplates] = useState([])
  const [total, setTotal]         = useState(0)
  const [loading, setLoading]     = useState(true)
  const [remixing, setRemixing]   = useState(null)   // template_id being remixed
  const [filterSrc, setFilterSrc] = useState('')
  const [filterTgt, setFilterTgt] = useState('')
  const [visible, setVisible]     = useState(false)

  useEffect(() => { setTimeout(() => setVisible(true), 80) }, [])

  const loadTemplates = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams({ limit: 20, offset: 0 })
      if (filterSrc) params.set('source', filterSrc)
      if (filterTgt) params.set('target', filterTgt)
      const res = await fetch(`${API}/templates?${params}`, {
        headers: { Authorization: `Bearer ${authToken}` },
      })
      if (!res.ok) return
      const data = await res.json()
      setTemplates(data.templates || [])
      setTotal(data.total || 0)
    } catch {
      // non-fatal
    } finally {
      setLoading(false)
    }
  }, [authToken, filterSrc, filterTgt])

  useEffect(() => { loadTemplates() }, [loadTemplates])

  const handleRemix = async (tmplId) => {
    if (remixing || !authToken) return
    setRemixing(tmplId)
    try {
      const res = await fetch(`${API}/templates/${tmplId}/remix`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${authToken}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      })
      if (!res.ok) return
      const arc = await res.json()
      onRemix(arc)
    } catch {
      // non-fatal
    } finally {
      setRemixing(null)
    }
  }

  const EMOTIONS = ['energetic','happy','euphoric','peaceful','focused','romantic',
                    'nostalgic','neutral','melancholic','sad','tense','angry']

  return (
    <div style={s.screen}>
      <div style={{
        ...s.landingWrap,
        opacity: visible ? 1 : 0,
        transform: visible ? 'none' : 'translateY(20px)',
        transition: 'all 0.9s cubic-bezier(0.16,1,0.3,1)',
        maxWidth: 780,
      }}>
        {/* Nav */}
        <div style={s.nav}>
          <span style={s.navBrand}>◈ flowstate</span>
          <button onClick={onBack} style={{ ...s.logoutBtn }}>← Back</button>
        </div>

        <div style={{ marginBottom: 24 }}>
          <h2 style={{ fontFamily: "'Syne', sans-serif", fontSize: 28, fontWeight: 700, color: '#e2e8f0', marginBottom: 6 }}>
            Discover Arcs
          </h2>
          <p style={{ color: 'rgba(255,255,255,0.45)', fontSize: 14 }}>
            Remix a shared emotional template with your own library — same journey, entirely your music.
          </p>
        </div>

        {/* Filters */}
        <div style={{ display: 'flex', gap: 10, marginBottom: 20, flexWrap: 'wrap' }}>
          {[
            { label: 'From', val: filterSrc, set: setFilterSrc },
            { label: 'To',   val: filterTgt, set: setFilterTgt },
          ].map(({ label, val, set }) => (
            <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{ fontSize: 12, color: 'rgba(255,255,255,0.4)' }}>{label}</span>
              <select
                value={val}
                onChange={e => set(e.target.value)}
                style={{
                  background: 'rgba(255,255,255,0.04)',
                  border: '1px solid rgba(255,255,255,0.12)',
                  borderRadius: 8,
                  color: val ? '#e2e8f0' : 'rgba(255,255,255,0.35)',
                  padding: '5px 10px',
                  fontSize: 12,
                  fontFamily: "'DM Sans', sans-serif",
                  cursor: 'pointer',
                  outline: 'none',
                }}
              >
                <option value="">Any emotion</option>
                {EMOTIONS.map(e => (
                  <option key={e} value={e} style={{ background: '#0d0921' }}>{e}</option>
                ))}
              </select>
            </div>
          ))}
          {(filterSrc || filterTgt) && (
            <button
              onClick={() => { setFilterSrc(''); setFilterTgt('') }}
              style={{ background: 'none', border: 'none', color: 'rgba(255,255,255,0.35)', cursor: 'pointer', fontSize: 12 }}
            >
              Clear
            </button>
          )}
        </div>

        {/* Template list */}
        {loading ? (
          <div style={{ color: 'rgba(255,255,255,0.3)', fontSize: 14, textAlign: 'center', padding: '40px 0' }}>
            Loading templates…
          </div>
        ) : templates.length === 0 ? (
          <div style={{ color: 'rgba(255,255,255,0.3)', fontSize: 14, textAlign: 'center', padding: '40px 0' }}>
            No templates yet — generate an arc and share it to be the first!
          </div>
        ) : (
          <>
            <div style={{ fontSize: 12, color: 'rgba(255,255,255,0.3)', marginBottom: 12 }}>
              {total} template{total !== 1 ? 's' : ''}
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {templates.map(tmpl => (
                <div
                  key={tmpl.id}
                  style={{
                    background: 'rgba(255,255,255,0.03)',
                    border: '1px solid rgba(255,255,255,0.08)',
                    borderRadius: 12,
                    padding: '14px 18px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    gap: 16,
                  }}
                >
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontWeight: 600, fontSize: 14, color: '#e2e8f0', marginBottom: 4, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {tmpl.display_name}
                    </div>
                    <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                      <span style={{ fontSize: 11, color: EMOTION_COLORS[tmpl.source_emotion] || '#a78bfa' }}>
                        {tmpl.source_emotion}
                      </span>
                      <span style={{ fontSize: 11, color: 'rgba(255,255,255,0.25)' }}>→</span>
                      <span style={{ fontSize: 11, color: EMOTION_COLORS[tmpl.target_emotion] || '#a78bfa' }}>
                        {tmpl.target_emotion}
                      </span>
                      <span style={{ fontSize: 11, color: 'rgba(255,255,255,0.25)' }}>·</span>
                      <span style={{ fontSize: 11, color: 'rgba(255,255,255,0.35)' }}>{tmpl.duration_mins} min</span>
                      <span style={{ fontSize: 11, color: 'rgba(255,255,255,0.25)' }}>·</span>
                      <span style={{ fontSize: 11, color: 'rgba(255,255,255,0.35)' }}>
                        {tmpl.remix_count} remix{tmpl.remix_count !== 1 ? 'es' : ''}
                      </span>
                      {tmpl.author && (
                        <>
                          <span style={{ fontSize: 11, color: 'rgba(255,255,255,0.25)' }}>·</span>
                          <span style={{ fontSize: 11, color: 'rgba(255,255,255,0.35)' }}>by {tmpl.author}</span>
                        </>
                      )}
                    </div>
                  </div>
                  <button
                    onClick={() => handleRemix(tmpl.id)}
                    disabled={remixing === tmpl.id}
                    style={{
                      background: 'rgba(139, 92, 246, 0.15)',
                      border: '1px solid rgba(139, 92, 246, 0.35)',
                      color: '#a78bfa',
                      borderRadius: 8,
                      padding: '6px 16px',
                      fontSize: 12,
                      cursor: remixing === tmpl.id ? 'default' : 'pointer',
                      fontFamily: "'DM Sans', sans-serif",
                      whiteSpace: 'nowrap',
                      flexShrink: 0,
                    }}
                  >
                    {remixing === tmpl.id ? '…' : 'Remix →'}
                  </button>
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  )
}

// ── Screen 6: Collaborative Arc Session ──────────────────────────────────────
function CollabScreen({ onBack, authToken, onArcReady }) {
  const EMOTIONS = Object.keys(EMOTION_COLORS)
  const [mode, setMode]           = useState('create') // 'create' | 'join'
  const [targetEmotion, setTarget] = useState('peaceful')
  const [duration, setDuration]   = useState(30)
  const [sourceEmotion, setSource] = useState('tense')
  const [inviteCode, setInviteCode] = useState('')
  const [joinCode, setJoinCode]   = useState('')
  const [session, setSession]     = useState(null) // session data after create/join
  const [error, setError]         = useState(null)
  const [generating, setGenerating] = useState(false)
  const [joinMsg, setJoinMsg]     = useState(null)
  const pollRef                   = useRef(null)

  const hdrs = { Authorization: `Bearer ${authToken}`, 'Content-Type': 'application/json' }

  // Poll session state while waiting as host
  useEffect(() => {
    if (!inviteCode || !authToken) return
    pollRef.current = setInterval(async () => {
      try {
        const r = await fetch(`${API}/collab/sessions/${inviteCode}`, { headers: hdrs })
        if (r.ok) setSession(await r.json())
      } catch {}
    }, 4000)
    return () => clearInterval(pollRef.current)
  }, [inviteCode])

  async function handleCreate() {
    setError(null)
    try {
      const r = await fetch(`${API}/collab/sessions`, {
        method: 'POST', headers: hdrs,
        body: JSON.stringify({ target_emotion: targetEmotion, duration_minutes: duration }),
      })
      if (!r.ok) { const d = await r.json(); throw new Error(d.detail || 'Failed') }
      const data = await r.json()
      setInviteCode(data.invite_code)
      // Also join with host's own source emotion
      await fetch(`${API}/collab/sessions/${data.invite_code}/join`, {
        method: 'POST', headers: hdrs,
        body: JSON.stringify({ source_emotion: sourceEmotion }),
      })
      const s2 = await fetch(`${API}/collab/sessions/${data.invite_code}`, { headers: hdrs })
      setSession(await s2.json())
    } catch (e) {
      setError(e.message)
    }
  }

  async function handleJoin() {
    setError(null)
    if (!joinCode.trim()) return
    try {
      const r = await fetch(`${API}/collab/sessions/${joinCode.trim().toUpperCase()}/join`, {
        method: 'POST', headers: hdrs,
        body: JSON.stringify({ source_emotion: sourceEmotion }),
      })
      if (!r.ok) { const d = await r.json(); throw new Error(d.detail || 'Not found') }
      const s = await fetch(`${API}/collab/sessions/${joinCode.trim().toUpperCase()}`, { headers: hdrs })
      setSession(await s.json())
      setInviteCode(joinCode.trim().toUpperCase())
      setJoinMsg(`Joined! You're contributing "${sourceEmotion}" to the group arc.`)
    } catch (e) {
      setError(e.message)
    }
  }

  async function handleGenerateArc() {
    setGenerating(true)
    setError(null)
    try {
      const r = await fetch(`${API}/collab/sessions/${inviteCode}/arc`, {
        method: 'POST', headers: hdrs,
      })
      if (!r.ok) { const d = await r.json(); throw new Error(d.detail || 'Generation failed') }
      const arc = await r.json()
      clearInterval(pollRef.current)
      onArcReady(arc)
    } catch (e) {
      setError(e.message)
      setGenerating(false)
    }
  }

  const cardStyle = { background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 16, padding: '20px 24px', marginBottom: 16 }

  return (
    <div style={s.screen}>
      <div style={{ width: '100%', maxWidth: 560, position: 'relative', zIndex: 1 }}>
        <button onClick={onBack} style={s.backBtn}>← back</button>

        <div style={{ fontFamily: "'Syne', sans-serif", fontSize: 28, fontWeight: 700, color: '#fff', marginBottom: 6, letterSpacing: '-0.5px' }}>
          Collaborative Arc
        </div>
        <p style={{ fontSize: 14, color: 'rgba(255,255,255,0.4)', marginBottom: 28, fontWeight: 300 }}>
          Everyone brings their emotion. One arc moves you all.
        </p>

        {/* Mode tabs */}
        {!inviteCode && (
          <div style={{ display: 'flex', gap: 8, marginBottom: 24 }}>
            {['create', 'join'].map(m => (
              <button key={m} onClick={() => setMode(m)} style={{
                flex: 1,
                background: mode === m ? 'rgba(139,92,246,0.18)' : 'rgba(255,255,255,0.03)',
                border: `1px solid ${mode === m ? 'rgba(139,92,246,0.5)' : 'rgba(255,255,255,0.08)'}`,
                color: mode === m ? '#c4b5fd' : 'rgba(255,255,255,0.4)',
                borderRadius: 10, padding: '9px 0', fontSize: 13, fontWeight: 600,
                cursor: 'pointer', fontFamily: "'DM Sans', sans-serif",
              }}>
                {m === 'create' ? '⊕ Start a session' : '↗ Join a session'}
              </button>
            ))}
          </div>
        )}

        {/* Create mode */}
        {!inviteCode && mode === 'create' && (
          <div>
            <div style={cardStyle}>
              <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.3)', letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 14 }}>
                Where do you want everyone to land?
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 20 }}>
                {EMOTIONS.map(e => (
                  <button key={e} onClick={() => setTarget(e)} style={{
                    background: targetEmotion === e ? EMOTION_COLORS[e] + '30' : 'rgba(255,255,255,0.04)',
                    border: `1px solid ${targetEmotion === e ? EMOTION_COLORS[e] + '80' : 'rgba(255,255,255,0.1)'}`,
                    color: targetEmotion === e ? EMOTION_COLORS[e] : 'rgba(255,255,255,0.5)',
                    borderRadius: 100, padding: '5px 14px', fontSize: 12, fontWeight: 600,
                    cursor: 'pointer', fontFamily: "'DM Sans', sans-serif",
                  }}>
                    {EMOTION_EMOJI[e]} {e}
                  </button>
                ))}
              </div>
              <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.3)', letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 14 }}>
                Your current state
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 20 }}>
                {EMOTIONS.map(e => (
                  <button key={e} onClick={() => setSource(e)} style={{
                    background: sourceEmotion === e ? EMOTION_COLORS[e] + '30' : 'rgba(255,255,255,0.04)',
                    border: `1px solid ${sourceEmotion === e ? EMOTION_COLORS[e] + '80' : 'rgba(255,255,255,0.1)'}`,
                    color: sourceEmotion === e ? EMOTION_COLORS[e] : 'rgba(255,255,255,0.5)',
                    borderRadius: 100, padding: '5px 14px', fontSize: 12, fontWeight: 600,
                    cursor: 'pointer', fontFamily: "'DM Sans', sans-serif",
                  }}>
                    {EMOTION_EMOJI[e]} {e}
                  </button>
                ))}
              </div>
              <div style={{ marginBottom: 4 }}>
                <span style={{ fontSize: 13, color: 'rgba(255,255,255,0.5)' }}>Duration: <b style={{ color: '#fff' }}>{duration} min</b></span>
                <input type="range" min={10} max={90} step={5} value={duration} onChange={e => setDuration(+e.target.value)}
                  className="mood-slider" style={{ display: 'block', width: '100%', marginTop: 8 }} />
              </div>
            </div>
            <button onClick={handleCreate} className="start-btn" style={{ ...s.startBtn, width: '100%', justifyContent: 'center' }}>
              Create session →
            </button>
          </div>
        )}

        {/* Join mode */}
        {!inviteCode && mode === 'join' && (
          <div>
            <div style={cardStyle}>
              <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.3)', letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 12 }}>
                Session invite code
              </div>
              <input
                value={joinCode} onChange={e => setJoinCode(e.target.value.toUpperCase())}
                placeholder="e.g. AZ3K7Q"
                maxLength={8}
                style={{
                  width: '100%', background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.12)',
                  borderRadius: 10, padding: '12px 16px', color: '#fff', fontSize: 18,
                  fontWeight: 700, letterSpacing: '0.15em', fontFamily: "'Syne', sans-serif",
                  outline: 'none', marginBottom: 16,
                }}
              />
              <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.3)', letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 12 }}>
                Your current state
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                {EMOTIONS.map(e => (
                  <button key={e} onClick={() => setSource(e)} style={{
                    background: sourceEmotion === e ? EMOTION_COLORS[e] + '30' : 'rgba(255,255,255,0.04)',
                    border: `1px solid ${sourceEmotion === e ? EMOTION_COLORS[e] + '80' : 'rgba(255,255,255,0.1)'}`,
                    color: sourceEmotion === e ? EMOTION_COLORS[e] : 'rgba(255,255,255,0.5)',
                    borderRadius: 100, padding: '5px 14px', fontSize: 12, fontWeight: 600,
                    cursor: 'pointer', fontFamily: "'DM Sans', sans-serif",
                  }}>
                    {EMOTION_EMOJI[e]} {e}
                  </button>
                ))}
              </div>
            </div>
            <button onClick={handleJoin} disabled={!joinCode.trim()} className="start-btn"
              style={{ ...s.startBtn, width: '100%', justifyContent: 'center', opacity: joinCode.trim() ? 1 : 0.4 }}>
              Join session →
            </button>
            {joinMsg && (
              <div style={{ marginTop: 14, fontSize: 13, color: '#34d399', background: 'rgba(16,185,129,0.08)', border: '1px solid rgba(16,185,129,0.2)', borderRadius: 10, padding: '10px 16px' }}>
                ✓ {joinMsg}
              </div>
            )}
          </div>
        )}

        {/* Session lobby — shown after create or join */}
        {inviteCode && session && (
          <div>
            <div style={{ ...cardStyle, background: 'rgba(139,92,246,0.06)', border: '1px solid rgba(139,92,246,0.2)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
                <div>
                  <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.3)', letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 4 }}>
                    Invite code
                  </div>
                  <div style={{ fontFamily: "'Syne', sans-serif", fontSize: 28, fontWeight: 800, color: '#c4b5fd', letterSpacing: '0.15em' }}>
                    {inviteCode}
                  </div>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.3)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 4 }}>
                    Destination
                  </div>
                  <div style={{ fontSize: 15, fontWeight: 700, color: EMOTION_COLORS[session.target_emotion] || '#a78bfa' }}>
                    {EMOTION_EMOJI[session.target_emotion]} {session.target_emotion}
                  </div>
                </div>
              </div>

              <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.3)', letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 12 }}>
                {session.participant_count} participant{session.participant_count !== 1 ? 's' : ''} in the session
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                {session.participants?.map((p, i) => (
                  <div key={p.user_id || i} style={{
                    display: 'flex', alignItems: 'center', gap: 6,
                    background: EMOTION_COLORS[p.source_emotion] + '18',
                    border: `1px solid ${EMOTION_COLORS[p.source_emotion] + '50'}`,
                    borderRadius: 100, padding: '5px 14px', fontSize: 12,
                  }}>
                    <span style={{ width: 7, height: 7, borderRadius: '50%', background: EMOTION_COLORS[p.source_emotion] || '#a78bfa', display: 'inline-block', flexShrink: 0 }} />
                    <span style={{ color: EMOTION_COLORS[p.source_emotion] || '#a78bfa', fontWeight: 600 }}>
                      {EMOTION_EMOJI[p.source_emotion]} {p.source_emotion}
                    </span>
                  </div>
                ))}
              </div>

              {session.aggregated_source && (
                <div style={{ marginTop: 14, fontSize: 12, color: 'rgba(255,255,255,0.5)', borderTop: '1px solid rgba(255,255,255,0.06)', paddingTop: 12 }}>
                  Group centroid: <span style={{ color: EMOTION_COLORS[session.aggregated_source] || '#a78bfa', fontWeight: 600 }}>
                    {EMOTION_EMOJI[session.aggregated_source]} {session.aggregated_source}
                  </span>
                </div>
              )}
            </div>

            {/* Generate button — only for host (session.host_user_id isn't exposed here, show for everyone but API will guard) */}
            {mode === 'create' && (
              <button
                onClick={handleGenerateArc}
                disabled={generating || session.participant_count < 1}
                className="start-btn"
                style={{
                  ...s.startBtn, width: '100%', justifyContent: 'center',
                  opacity: generating ? 0.6 : 1,
                  background: generating ? 'rgba(139,92,246,0.3)' : undefined,
                }}
              >
                {generating ? 'Generating group arc…' : `Generate arc for ${session.participant_count} participant${session.participant_count !== 1 ? 's' : ''} →`}
              </button>
            )}
            {mode === 'join' && (
              <div style={{ fontSize: 13, color: 'rgba(255,255,255,0.4)', textAlign: 'center', padding: '16px 0' }}>
                Waiting for the host to generate the arc…
              </div>
            )}
          </div>
        )}

        {error && (
          <div style={{ marginTop: 12, fontSize: 13, color: '#fca5a5', background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.2)', borderRadius: 10, padding: '10px 16px' }}>
            {error}
          </div>
        )}
      </div>
    </div>
  )
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function getTimeOfDay() {
  const h = new Date().getHours()
  if (h < 12) return 'morning'
  if (h < 17) return 'afternoon'
  return 'evening'
}

// ── Main Dashboard ────────────────────────────────────────────────────────────
export default function Dashboard() {
  const [user, setUser]               = useState(null)
  const [stats, setStats]             = useState(null)
  const [readiness, setReadiness]     = useState(null)
  const [screen, setScreen]           = useState('landing') // landing | input | loading | result | discover | collab
  const [arc, setArc]                 = useState(null)
  const [sessionId, setSessionId]     = useState(null)
  const [moodText, setMoodText]       = useState('')
  const [waitTrack, setWaitTrack]     = useState(null)
  const [error, setError]             = useState(null)
  const [spotifyToken, setSpotifyToken] = useState(null)
  const [modelStatus, setModelStatus]   = useState(null)
  const [reclassifyMsg, setReclassifyMsg] = useState(null)
  const [insights, setInsights]         = useState(null)
  const [langStats, setLangStats]       = useState(null)
  const navigate                  = useNavigate()
  const [searchParams]            = useSearchParams()

  const token = useCallback(() =>
    searchParams.get('token') || localStorage.getItem('flowstate_token'), [searchParams])

  useEffect(() => {
    const t = searchParams.get('token')
    if (t) {
      localStorage.setItem('flowstate_token', t)
      window.history.replaceState({}, '', '/dashboard')
    }
    const tok = t || localStorage.getItem('flowstate_token')
    if (!tok) { navigate('/'); return }

    const hdrs = { Authorization: `Bearer ${tok}` }

    fetch(`${API}/auth/me`, { headers: hdrs })
      .then(r => { if (!r.ok) throw new Error('Session expired'); return r.json() })
      .then(setUser)
      .catch(() => { localStorage.removeItem('flowstate_token'); navigate('/') })

    // Fetch Spotify access token for Web Playback SDK (non-fatal if unavailable)
    fetch(`${API}/auth/spotify-token`, { headers: hdrs })
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d?.access_token) setSpotifyToken(d.access_token) })
      .catch(() => {})

    // Load stats + emotions + readiness + model status + insights + language stats in parallel
    Promise.all([
      fetch(`${API}/tracks/stats`, { headers: hdrs }).then(r => r.json()),
      fetch(`${API}/tracks/emotions`, { headers: hdrs }).then(r => r.json()),
      fetch(`${API}/tracks/readiness`, { headers: hdrs }).then(r => r.json()),
      fetch(`${API}/tracks/model-status`, { headers: hdrs }).then(r => r.ok ? r.json() : null).catch(() => null),
      fetch(`${API}/arc/insights`, { headers: hdrs }).then(r => r.ok ? r.json() : null).catch(() => null),
      fetch(`${API}/tracks/language-stats`, { headers: hdrs }).then(r => r.ok ? r.json() : null).catch(() => null),
    ]).then(([statsData, emotionData, readinessData, modelData, insightsData, langData]) => {
      setStats({ ...statsData, distribution: emotionData.distribution })
      setReadiness(readinessData)
      setModelStatus(modelData)
      setInsights(insightsData)
      setLangStats(langData)
      // Pick a peaceful/neutral track for the loading screen
      const peaceful = emotionData.distribution?.find(e => e.emotion_label === 'peaceful')
      if (peaceful) {
        fetch(`${API}/tracks/by-emotion/peaceful?limit=5`, { headers: hdrs })
          .then(r => r.json())
          .then(data => { if (data.tracks?.[0]) setWaitTrack(data.tracks[0].spotify_id) })
          .catch(() => {})
      }
    }).catch(() => {})
  }, [navigate, searchParams])

  // Poll readiness every 8s until library is ready
  useEffect(() => {
    if (!readiness || readiness.state === 'ready') return
    const tok = localStorage.getItem('flowstate_token')
    if (!tok) return
    const interval = setInterval(() => {
      fetch(`${API}/tracks/readiness`, { headers: { Authorization: `Bearer ${tok}` } })
        .then(r => r.json())
        .then(data => {
          setReadiness(data)
          if (data.state === 'ready') {
            // Refresh stats too now that emotions are available
            Promise.all([
              fetch(`${API}/tracks/stats`, { headers: { Authorization: `Bearer ${tok}` } }).then(r => r.json()),
              fetch(`${API}/tracks/emotions`, { headers: { Authorization: `Bearer ${tok}` } }).then(r => r.json()),
            ]).then(([s, e]) => setStats({ ...s, distribution: e.distribution })).catch(() => {})
          }
        })
        .catch(() => {})
    }, 8000)
    return () => clearInterval(interval)
  }, [readiness?.state])

  async function handleReclassify() {
    const tok = token()
    if (!tok) return
    const hdrs = { Authorization: `Bearer ${tok}` }
    try {
      const res = await fetch(`${API}/tracks/reclassify`, { method: 'POST', headers: hdrs })
      if (!res.ok) throw new Error('Reclassification failed')
      const data = await res.json()
      setReclassifyMsg(`${data.updated} tracks reclassified with ML model`)
      setTimeout(() => setReclassifyMsg(null), 5000)
      // Refresh stats + emotions + readiness + model status + insights
      Promise.all([
        fetch(`${API}/tracks/stats`, { headers: hdrs }).then(r => r.json()),
        fetch(`${API}/tracks/emotions`, { headers: hdrs }).then(r => r.json()),
        fetch(`${API}/tracks/readiness`, { headers: hdrs }).then(r => r.json()),
        fetch(`${API}/tracks/model-status`, { headers: hdrs }).then(r => r.ok ? r.json() : null).catch(() => null),
        fetch(`${API}/arc/insights`, { headers: hdrs }).then(r => r.ok ? r.json() : null).catch(() => null),
      ]).then(([s, e, r, m, ins]) => {
        setStats({ ...s, distribution: e.distribution })
        setReadiness(r)
        setModelStatus(m)
        setInsights(ins)
      }).catch(() => {})
    } catch {
      setError('Reclassification failed — is the model trained?')
      setTimeout(() => setError(null), 4000)
    }
  }

  async function handleGenerateArc(text, duration, sourceEmotion, targetEmotion, languageFilter) {
    setMoodText(text)
    setScreen('loading')
    setError(null)

    const tok = token()
    const body = { mood_text: text, duration_minutes: duration }
    if (sourceEmotion && targetEmotion) {
      body.source_emotion = sourceEmotion
      body.target_emotion = targetEmotion
    }
    if (languageFilter?.length) {
      body.language_filter = languageFilter
    }
    try {
      const res = await fetch(`${API}/arc/generate`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${tok}`, 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail?.message || 'Arc generation failed')
      }
      const data = await res.json()
      // 202 is res.ok but means library_not_ready — FastAPI wraps it in detail
      if (data.detail?.error) {
        throw new Error(data.detail?.message || data.detail?.error || 'Arc generation failed')
      }
      setArc(data)
      setScreen('result')

      // Create session record asynchronously — non-blocking, non-fatal
      const segmentOf = (() => {
        let offset = 0
        const map = {}
        data.segments.forEach((seg, si) => {
          for (let i = 0; i < seg.track_count; i++) map[offset + i] = si
          offset += seg.track_count
        })
        return map
      })()
      fetch(`${API}/sessions`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${tok}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({
          source_emotion: data.arc_path[0],
          target_emotion: data.arc_path[data.arc_path.length - 1],
          duration_mins: Math.round(data.total_duration_ms / 60000),
          arc_path: data.arc_path,
          tracks: data.tracks.map((t, i) => ({
            track_id: t.spotify_id,
            position: i,
            emotion_label: t.emotion_label,
            arc_segment: segmentOf[i] ?? null,
          })),
        }),
      })
        .then(r => r.ok ? r.json() : null)
        .then(d => { if (d?.session_id) setSessionId(d.session_id) })
        .catch(() => {})
    } catch (e) {
      setError(e.message)
      setScreen('input')
    }
  }

  if (!user) return (
    <div style={{ minHeight: '100vh', background: '#080612', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ color: 'rgba(255,255,255,0.4)', fontFamily: 'DM Sans, sans-serif', fontSize: '15px' }}>Loading your profile…</div>
    </div>
  )

  return (
    <div className="dash-root" style={{ minHeight: '100vh', background: 'radial-gradient(ellipse at 20% 50%, #1a0533 0%, #080612 50%, #030310 100%)', fontFamily: "'DM Sans', sans-serif", position: 'relative', overflow: 'hidden' }}>
      <style>{dashCss}</style>
      <ConstellationBg />

      {screen === 'landing'  && <LandingScreen user={user} stats={stats} readiness={readiness} modelStatus={modelStatus} insights={insights} langStats={langStats} onStart={() => setScreen('input')} onDiscover={() => setScreen('discover')} onCollab={() => setScreen('collab')} onReclassify={handleReclassify} />}
      {screen === 'input'    && <MoodInputScreen onSubmit={handleGenerateArc} onBack={() => setScreen('landing')} authToken={token()} />}
      {screen === 'loading'  && <LoadingScreen moodText={moodText} waitTrack={waitTrack} />}
      {screen === 'result'   && arc && (
        <ArcErrorBoundary onReset={() => { setArc(null); setSessionId(null); setScreen('input') }}>
          <ArcResultScreen arc={arc} spotifyToken={spotifyToken} sessionId={sessionId} authToken={token()} onReset={() => { setArc(null); setSessionId(null); setScreen('input') }} />
        </ArcErrorBoundary>
      )}
      {screen === 'discover' && <DiscoverScreen authToken={token()} onBack={() => setScreen('landing')} onRemix={(arc) => { setArc(arc); setScreen('result') }} />}
      {screen === 'collab'   && <CollabScreen authToken={token()} onBack={() => setScreen('landing')} onArcReady={(arc) => { setArc(arc); setScreen('result') }} />}

      {error && (
        <div style={{ position: 'fixed', bottom: '24px', left: '50%', transform: 'translateX(-50%)', background: 'rgba(239,68,68,0.15)', border: '1px solid rgba(239,68,68,0.4)', color: '#fca5a5', padding: '12px 24px', borderRadius: '100px', fontSize: '14px', zIndex: 100 }}>
          {error}
        </div>
      )}
      {reclassifyMsg && (
        <div style={{ position: 'fixed', bottom: '24px', left: '50%', transform: 'translateX(-50%)', background: 'rgba(16,185,129,0.15)', border: '1px solid rgba(16,185,129,0.4)', color: '#34d399', padding: '12px 24px', borderRadius: '100px', fontSize: '14px', zIndex: 100 }}>
          ✓ {reclassifyMsg}
        </div>
      )}
    </div>
  )
}

// ── CSS ───────────────────────────────────────────────────────────────────────
const dashCss = `
  @import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=DM+Sans:ital,opsz,wght@0,9..40,300;0,9..40,400;0,9..40,600;1,9..40,300&display=swap');
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #080612; }

  .start-btn:hover { background: linear-gradient(135deg, #7c3aed, #0891b2) !important; transform: translateY(-2px); box-shadow: 0 12px 40px rgba(139,92,246,0.4) !important; }
  .start-btn { transition: all 0.2s ease !important; }

  .hint-chip:hover { background: rgba(139,92,246,0.2) !important; border-color: rgba(139,92,246,0.5) !important; color: rgba(255,255,255,0.9) !important; }
  .hint-chip { transition: all 0.15s ease !important; }

  .generate-btn:hover:not(:disabled) { background: linear-gradient(135deg, #7c3aed, #0891b2) !important; transform: translateY(-2px); }
  .generate-btn { transition: all 0.2s ease !important; }

  .track-row:hover { background: rgba(255,255,255,0.04) !important; }
  .track-row { transition: background 0.15s ease !important; }

  @keyframes emotionPulse {
    0%, 100% { box-shadow: 0 0 8px var(--emotion-primary, #8b5cf6), inset 0 0 6px rgba(139,92,246,0.08); }
    50%       { box-shadow: 0 0 20px var(--emotion-primary, #8b5cf6), inset 0 0 10px rgba(139,92,246,0.12); }
  }
  .playing-track-row { animation: emotionPulse 2.4s ease-in-out infinite !important; }

  @keyframes pulseOrb {
    0%, 100% { transform: scale(1); opacity: 0.8; box-shadow: 0 0 40px rgba(139,92,246,0.4); }
    50% { transform: scale(1.1); opacity: 1; box-shadow: 0 0 80px rgba(139,92,246,0.7); }
  }
  .pulse-orb { animation: pulseOrb 2s ease-in-out infinite !important; }

  .mood-slider { -webkit-appearance: none; appearance: none; height: 3px; background: rgba(139,92,246,0.3); border-radius: 100px; outline: none; width: 100%; }
  .mood-slider::-webkit-slider-thumb { -webkit-appearance: none; width: 18px; height: 18px; border-radius: 50%; background: #8b5cf6; cursor: pointer; box-shadow: 0 0 12px rgba(139,92,246,0.5); }

  ::-webkit-scrollbar { width: 4px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: rgba(139,92,246,0.3); border-radius: 2px; }

  :root { --emotion-primary: #8b5cf6; }
  .dash-root { transition: background 1.2s ease !important; }
`

// ── Styles ────────────────────────────────────────────────────────────────────
const s = {
  screen: { position: 'relative', zIndex: 1, minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '24px' },

  // Landing
  landingWrap: { width: '100%', maxWidth: '680px' },
  nav: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '64px' },
  navBrand: { fontFamily: "'Syne', sans-serif", fontSize: '14px', fontWeight: '600', letterSpacing: '0.2em', textTransform: 'uppercase', color: 'rgba(255,255,255,0.4)' },
  logoutBtn: { background: 'transparent', border: '1px solid rgba(255,255,255,0.12)', color: 'rgba(255,255,255,0.4)', borderRadius: '100px', padding: '6px 16px', fontSize: '12px', cursor: 'pointer', letterSpacing: '0.05em' },
  hero: { marginBottom: '48px' },
  greeting: { fontFamily: "'DM Sans', sans-serif", fontSize: '15px', color: 'rgba(255,255,255,0.4)', marginBottom: '16px', fontWeight: '300' },
  accentText: { color: '#8b5cf6', fontWeight: '400' },
  heroTitle: { fontFamily: "'Syne', sans-serif", fontSize: 'clamp(40px, 6vw, 64px)', fontWeight: '800', color: '#ffffff', lineHeight: 1.05, letterSpacing: '-1.5px', marginBottom: '20px' },
  heroAccent: { background: 'linear-gradient(90deg, #8b5cf6, #06b6d4)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' },
  heroSub: { fontSize: '17px', color: 'rgba(255,255,255,0.4)', lineHeight: 1.7, marginBottom: '40px', fontWeight: '300', maxWidth: '440px' },
  startBtn: { display: 'inline-flex', alignItems: 'center', gap: '10px', padding: '16px 36px', background: 'linear-gradient(135deg, #8b5cf6, #0891b2)', color: 'white', border: 'none', borderRadius: '100px', fontSize: '16px', fontWeight: '600', cursor: 'pointer', letterSpacing: '0.01em', boxShadow: '0 8px 32px rgba(139,92,246,0.3)' },
  arrow: { fontSize: '18px' },
  statsRow: { display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '12px', marginBottom: '32px' },
  statCard: { background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: '16px', padding: '20px 16px', textAlign: 'center' },
  statVal: { fontFamily: "'Syne', sans-serif", fontSize: '28px', fontWeight: '700', color: '#ffffff', marginBottom: '4px' },
  statLabel: { fontSize: '12px', color: 'rgba(255,255,255,0.35)', letterSpacing: '0.08em', textTransform: 'uppercase' },
  sectionLabel: { fontSize: '11px', color: 'rgba(255,255,255,0.3)', letterSpacing: '0.12em', textTransform: 'uppercase', marginBottom: '12px' },
  emotionGrid: {},
  emotionPills: { display: 'flex', flexWrap: 'wrap', gap: '8px' },
  emotionPill: { display: 'flex', alignItems: 'center', gap: '6px', padding: '7px 14px', borderRadius: '100px', border: '1px solid', fontSize: '13px' },

  // Input screen
  inputWrap: { width: '100%', maxWidth: '560px' },
  backBtn: { background: 'transparent', border: 'none', color: 'rgba(255,255,255,0.3)', fontSize: '13px', cursor: 'pointer', marginBottom: '40px', letterSpacing: '0.05em', padding: 0 },
  inputHeader: { marginBottom: '32px' },
  inputLabel: { fontFamily: "'Syne', sans-serif", fontSize: '32px', fontWeight: '700', color: '#ffffff', marginBottom: '10px', letterSpacing: '-0.5px' },
  inputSub: { fontSize: '15px', color: 'rgba(255,255,255,0.4)', fontWeight: '300' },
  textareaWrap: { background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '20px', padding: '20px', marginBottom: '24px', transition: 'box-shadow 0.2s ease', position: 'relative' },
  textarea: { width: '100%', background: 'transparent', border: 'none', outline: 'none', color: '#ffffff', fontSize: '17px', lineHeight: 1.6, resize: 'none', fontFamily: "'DM Sans', sans-serif", fontWeight: '300' },
  charCount: { fontSize: '11px', color: 'rgba(255,255,255,0.2)', textAlign: 'right', marginTop: '8px' },
  hintsWrap: { marginBottom: '32px' },
  hintsLabel: { fontSize: '11px', color: 'rgba(255,255,255,0.3)', letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: '10px' },
  hints: { display: 'flex', flexDirection: 'column', gap: '8px' },
  hintChip: { background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: '12px', padding: '10px 16px', color: 'rgba(255,255,255,0.5)', fontSize: '13px', cursor: 'pointer', textAlign: 'left', fontFamily: "'DM Sans', sans-serif" },
  durationWrap: { marginBottom: '36px' },
  durationLabel: { fontSize: '14px', color: 'rgba(255,255,255,0.5)', marginBottom: '14px' },
  slider: { width: '100%', marginBottom: '8px' },
  sliderMarks: { display: 'flex', justifyContent: 'space-between' },
  sliderMark: { fontSize: '11px', color: 'rgba(255,255,255,0.3)' },
  generateBtn: { width: '100%', padding: '16px', background: 'linear-gradient(135deg, #8b5cf6, #0891b2)', color: 'white', border: 'none', borderRadius: '100px', fontSize: '16px', fontWeight: '600', letterSpacing: '0.01em', boxShadow: '0 8px 32px rgba(139,92,246,0.3)' },

  // Loading screen
  loadingWrap: { textAlign: 'center', width: '100%', maxWidth: '460px' },
  loadingTop: { marginBottom: '48px' },
  loadingOrb: { width: '72px', height: '72px', borderRadius: '50%', background: 'radial-gradient(circle, #8b5cf6, #0891b2)', margin: '0 auto 28px', boxShadow: '0 0 40px rgba(139,92,246,0.4)' },
  loadingStatus: { fontFamily: "'Syne', sans-serif", fontSize: '20px', fontWeight: '600', color: '#ffffff', marginBottom: '12px' },
  loadingMood: { fontSize: '14px', color: 'rgba(255,255,255,0.35)', fontStyle: 'italic', maxWidth: '320px', margin: '0 auto' },
  waitMusicWrap: { textAlign: 'left' },
  waitMusicLabel: { fontSize: '12px', color: 'rgba(255,255,255,0.3)', letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: '14px', textAlign: 'center' },
  spotifyEmbed: { borderRadius: '16px', overflow: 'hidden', boxShadow: '0 8px 32px rgba(0,0,0,0.4)' },

  // Arc result
  arcWrap: { width: '100%', maxWidth: '720px', paddingBottom: '60px' },
  arcHeader: { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '36px' },
  arcInterpret: { fontFamily: "'Syne', sans-serif", fontSize: '22px', fontWeight: '700', color: '#ffffff', marginBottom: '6px', letterSpacing: '-0.3px' },
  arcMeta: { fontSize: '13px', color: 'rgba(255,255,255,0.35)' },
  newArcBtn: { background: 'rgba(139,92,246,0.15)', border: '1px solid rgba(139,92,246,0.3)', color: '#a78bfa', borderRadius: '100px', padding: '8px 20px', fontSize: '13px', cursor: 'pointer', whiteSpace: 'nowrap', flexShrink: 0 },

  pathWrap: { display: 'flex', alignItems: 'center', gap: '0', marginBottom: '36px', overflowX: 'auto', paddingBottom: '8px' },
  pathNode: { display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '8px', flexShrink: 0 },
  pathBubble: { width: '52px', height: '52px', borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center' },
  pathLabel: { fontSize: '11px', fontWeight: '600', letterSpacing: '0.05em', textTransform: 'uppercase' },
  pathArrow: { display: 'flex', alignItems: 'center', gap: '0', flex: 1, minWidth: '32px', marginBottom: '20px' },
  pathLine: { height: '1.5px', flex: 1 },
  pathChevron: { fontSize: '16px', color: 'rgba(255,255,255,0.2)', marginLeft: '2px' },

  curveWrap: { background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)', borderRadius: '16px', padding: '20px 20px 8px', marginBottom: '28px' },
  curveLabel: { fontSize: '11px', color: 'rgba(255,255,255,0.3)', letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: '12px' },
  curveAxis: { display: 'flex', justifyContent: 'space-between', fontSize: '10px', color: 'rgba(255,255,255,0.2)', marginTop: '4px' },

  segmentsWrap: { display: 'flex', flexDirection: 'column', gap: '8px' },
  segment: { background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.07)', borderRadius: '16px', overflow: 'hidden' },
  segHeader: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '16px 20px', cursor: 'pointer' },
  segLeft: { display: 'flex', alignItems: 'center', gap: '12px' },
  segDot: { width: '8px', height: '8px', borderRadius: '50%', flexShrink: 0 },
  segEmotion: { fontSize: '14px', fontWeight: '600', color: 'rgba(255,255,255,0.9)', textTransform: 'capitalize' },
  segCount: { fontSize: '12px', color: 'rgba(255,255,255,0.3)', background: 'rgba(255,255,255,0.06)', padding: '2px 10px', borderRadius: '100px' },
  segDir: { fontSize: '12px' },

  trackList: { borderTop: '1px solid rgba(255,255,255,0.06)', padding: '8px 0' },
  trackRow: { display: 'flex', alignItems: 'center', gap: '12px', padding: '10px 20px', borderRadius: '0', cursor: 'default' },
  trackNum: { fontSize: '12px', color: 'rgba(255,255,255,0.2)', width: '20px', textAlign: 'right', flexShrink: 0 },
  trackInfo: { flex: 1, minWidth: 0 },
  trackTitle: { fontSize: '14px', color: '#ffffff', fontWeight: '500', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' },
  trackArtist: { fontSize: '12px', color: '#cbd5e1', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' },
  trackMeta: { display: 'flex', alignItems: 'center', gap: '12px', flexShrink: 0 },
  energyBar: { width: '52px', height: '3px', background: 'rgba(255,255,255,0.1)', borderRadius: '2px', overflow: 'hidden' },
  energyFill: { height: '100%', borderRadius: '2px', transition: 'width 0.3s ease' },
  trackDur: { fontSize: '11px', color: 'rgba(255,255,255,0.3)', width: '36px', textAlign: 'right', flexShrink: 0 },
  spotifyLink: { color: '#1DB954', display: 'flex', alignItems: 'center', flexShrink: 0, opacity: 0.7 },
  warning: { marginTop: '16px', fontSize: '13px', color: 'rgba(251,191,36,0.7)', background: 'rgba(251,191,36,0.08)', border: '1px solid rgba(251,191,36,0.2)', borderRadius: '12px', padding: '12px 16px' },
}
