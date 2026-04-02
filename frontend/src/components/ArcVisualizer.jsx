/**
 * ArcVisualizer — Flowstate
 * --------------------------
 * Arc chart rendered as React SVG (declarative).
 * D3 is used only for scale/line/area computation, not DOM manipulation.
 */

import * as d3 from 'd3'
import { useEffect, useRef, useState } from 'react'

const EMOTION_COLORS = {
  energetic:   '#f59e0b', happy:       '#10b981', euphoric:    '#8b5cf6',
  peaceful:    '#06b6d4', focused:     '#3b82f6', romantic:    '#ec4899',
  nostalgic:   '#f97316', neutral:     '#6b7280', melancholic: '#6366f1',
  sad:         '#94a3b8', tense:       '#ef4444', angry:       '#dc2626',
}
const ec = (e) => EMOTION_COLORS[e] ?? '#8b5cf6'

const H   = 160
const PAD = { top: 22, bottom: 28, left: 36, right: 16 }

export default function ArcVisualizer({
  tracks = [],
  segments = [],
  arcPath = [],
  playingIndex = null,
  onTrackClick,
}) {
  const containerRef = useRef(null)
  const [width, setWidth]     = useState(680)
  const [tooltip, setTooltip] = useState(null)

  // Responsive width
  useEffect(() => {
    if (!containerRef.current) return
    const ro = new ResizeObserver(([e]) => setWidth(Math.floor(e.contentRect.width)))
    ro.observe(containerRef.current)
    return () => ro.disconnect()
  }, [])

  if (!tracks.length || width < 100) {
    return <div ref={containerRef} style={{ width: '100%', height: H }} />
  }

  const innerW = width  - PAD.left - PAD.right
  const innerH = H      - PAD.top  - PAD.bottom
  const n      = tracks.length

  const xScale = d3.scaleLinear().domain([0, Math.max(n - 1, 1)]).range([0, innerW])
  const yScale = d3.scaleLinear().domain([0, 1]).range([innerH, 0])

  const curve    = d3.curveCatmullRom.alpha(0.5)
  const lineGen  = d3.line().x((_, i) => xScale(i)).y(d => yScale(d.energy ?? 0.5)).curve(curve)
  const areaGen  = d3.area().x((_, i) => xScale(i)).y0(innerH).y1(d => yScale(d.energy ?? 0.5)).curve(curve)
  const valGen   = d3.line().x((_, i) => xScale(i)).y(d => yScale(d.valence ?? d.energy ?? 0.5)).curve(curve)

  const energyPath  = lineGen(tracks) || ''
  const fillPath    = areaGen(tracks) || ''
  const valencePath = valGen(tracks)  || ''

  // Segment band layout
  let cursor = 0
  const bands = segments.map(seg => {
    const start = cursor
    const end   = Math.min(cursor + seg.track_count - 1, n - 1)
    cursor += seg.track_count
    return { ...seg, start, end }
  }).filter(b => b.start < n)

  // Playing dot position
  const pIdx  = playingIndex != null && playingIndex < n ? playingIndex : null
  const pColor = pIdx != null ? ec(tracks[pIdx]?.emotion_label) : '#8b5cf6'
  const pX    = pIdx != null ? xScale(pIdx) : -999
  const pY    = pIdx != null ? yScale(tracks[pIdx]?.energy ?? 0.5) : innerH / 2

  // Gradient stops
  const gradStartColor = ec(arcPath[0] || 'neutral')
  const gradEndColor   = ec(arcPath[arcPath.length - 1] || 'neutral')

  const handleMouseMove = (e) => {
    const rect = e.currentTarget.getBoundingClientRect()
    const mx   = e.clientX - rect.left - PAD.left
    const idx  = Math.round(xScale.invert(mx))
    const ci   = Math.max(0, Math.min(n - 1, idx))
    setTooltip({ x: PAD.left + xScale(ci), y: PAD.top + yScale(tracks[ci]?.energy ?? 0.5), track: tracks[ci], index: ci })
  }

  return (
    <div ref={containerRef} style={{ position: 'relative', width: '100%', userSelect: 'none' }}>

      {/* Legend */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 6 }}>
        <span style={{ color: 'rgba(255,255,255,0.35)', fontSize: 11, fontFamily: 'DM Sans, sans-serif' }}>Energy arc</span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 5, color: 'rgba(148,163,184,0.55)', fontSize: 10, fontFamily: 'DM Sans, sans-serif' }}>
          <svg width="20" height="6"><line x1="0" y1="3" x2="20" y2="3" stroke="rgba(148,163,184,0.45)" strokeWidth="1.5" strokeDasharray="3,4"/></svg>
          valence
        </span>
      </div>

      <svg
        width={width}
        height={H}
        style={{ display: 'block', overflow: 'visible', cursor: onTrackClick ? 'pointer' : 'default' }}
        onMouseMove={handleMouseMove}
        onMouseLeave={() => setTooltip(null)}
        onClick={(e) => {
          if (!onTrackClick) return
          const rect = e.currentTarget.getBoundingClientRect()
          const mx   = e.clientX - rect.left - PAD.left
          const idx  = Math.round(xScale.invert(mx))
          onTrackClick(Math.max(0, Math.min(n - 1, idx)))
        }}
      >
        <defs>
          <filter id="arc-glow" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="3" result="blur"/>
            <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
          </filter>
          <linearGradient id="arc-fill-grad" x1="0%" y1="0%" x2="0%" y2="100%">
            <stop offset="0%"   stopColor="rgba(139,92,246,0.22)"/>
            <stop offset="100%" stopColor="rgba(139,92,246,0)"/>
          </linearGradient>
          <linearGradient id="arc-line-grad" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%"   stopColor={gradStartColor}/>
            <stop offset="100%" stopColor={gradEndColor}/>
          </linearGradient>
        </defs>

        <g transform={`translate(${PAD.left},${PAD.top})`}>

          {/* Segment bands */}
          {bands.map(b => (
            <g key={b.emotion + b.start}>
              <rect
                x={xScale(b.start)} y={0}
                width={xScale(b.end) - xScale(b.start)} height={innerH}
                fill={ec(b.emotion)} opacity={0.07}
              />
              {b.start > 0 && (
                <line x1={xScale(b.start)} y1={0} x2={xScale(b.start)} y2={innerH}
                  stroke={ec(b.emotion)} strokeWidth={0.5} opacity={0.25}/>
              )}
              <text
                x={xScale(b.start) + (xScale(b.end) - xScale(b.start)) / 2} y={-6}
                textAnchor="middle" fontSize={9} fontFamily="DM Sans, sans-serif"
                fill={ec(b.emotion)} opacity={0.8}
              >{b.emotion}</text>
            </g>
          ))}

          {/* Y-axis guide lines */}
          {[innerH * 0.75, innerH * 0.5, innerH * 0.25].map((y, i) => (
            <line key={i} x1={0} y1={y} x2={innerW} y2={y}
              stroke="rgba(255,255,255,0.06)" strokeWidth={1}/>
          ))}

          {/* Y-axis labels */}
          <text x={-4} y={2} textAnchor="end" dominantBaseline="hanging"
            fontSize={9} fontFamily="DM Sans, sans-serif" fill="rgba(255,255,255,0.3)">hi</text>
          <text x={-4} y={innerH} textAnchor="end" dominantBaseline="auto"
            fontSize={9} fontFamily="DM Sans, sans-serif" fill="rgba(255,255,255,0.3)">lo</text>

          {/* Fill area */}
          <path d={fillPath} fill="url(#arc-fill-grad)"/>

          {/* Valence line */}
          <path d={valencePath} fill="none"
            stroke="rgba(148,163,184,0.35)" strokeWidth={1.5} strokeDasharray="3,4"/>

          {/* Energy line */}
          <path d={energyPath} fill="none"
            stroke="url(#arc-line-grad)" strokeWidth={2.5} strokeLinecap="round"/>

          {/* Track dots */}
          {tracks.map((t, i) => (
            <circle
              key={i}
              cx={xScale(i)} cy={yScale(t.energy ?? 0.5)}
              r={3.5}
              fill={ec(t.emotion_label)}
              opacity={0.85}
              cursor={onTrackClick ? 'pointer' : 'default'}
              onClick={e => { e.stopPropagation(); onTrackClick?.(i) }}
            />
          ))}

          {/* Playing indicator */}
          {pIdx != null && (
            <>
              <line x1={pX} y1={0} x2={pX} y2={innerH}
                stroke={pColor} strokeWidth={1} opacity={0.5}/>
              <circle cx={pX} cy={pY} r={7}
                fill={pColor} filter="url(#arc-glow)" opacity={1}/>
            </>
          )}
        </g>
      </svg>

      {/* Tooltip */}
      {tooltip && (
        <div style={{
          position: 'absolute',
          left: Math.min(tooltip.x, width - 170),
          top: Math.max(0, tooltip.y - 60),
          background: 'rgba(10,6,20,0.95)',
          border: `1px solid ${ec(tooltip.track?.emotion_label)}55`,
          borderRadius: 8,
          padding: '8px 12px',
          pointerEvents: 'none',
          zIndex: 10,
          minWidth: 160,
          boxShadow: '0 4px 20px rgba(0,0,0,0.5)',
        }}>
          <div style={{ color: '#e2e8f0', fontSize: 12, fontWeight: 600, fontFamily: 'DM Sans, sans-serif', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 140 }}>
            {tooltip.track?.title}
          </div>
          <div style={{ color: '#94a3b8', fontSize: 11, fontFamily: 'DM Sans, sans-serif', marginTop: 2 }}>
            {tooltip.track?.artist}
          </div>
          <div style={{ display: 'flex', gap: 8, marginTop: 6 }}>
            <span style={{ background: `${ec(tooltip.track?.emotion_label)}22`, color: ec(tooltip.track?.emotion_label), fontSize: 10, padding: '2px 6px', borderRadius: 4, fontFamily: 'DM Sans, sans-serif' }}>
              {tooltip.track?.emotion_label}
            </span>
            <span style={{ color: '#64748b', fontSize: 10, fontFamily: 'DM Sans, sans-serif' }}>
              E {Math.round((tooltip.track?.energy ?? 0) * 100)}%
              · V {Math.round((tooltip.track?.valence ?? 0) * 100)}%
            </span>
          </div>
          {onTrackClick && (
            <div style={{ color: '#475569', fontSize: 9, marginTop: 4, fontFamily: 'DM Sans, sans-serif' }}>click to play</div>
          )}
        </div>
      )}
    </div>
  )
}
