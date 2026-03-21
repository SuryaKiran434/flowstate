/**
 * ArcVisualizer — Flowstate
 * ---------------------------
 * D3-powered arc chart. Renders energy + valence curves across all arc tracks,
 * with segment color bands, animated draw-in, hover tooltips, and a live
 * playhead that tracks the SpotifyPlayer position.
 *
 * Props:
 *   tracks        {Array}    arc.tracks flat list — {spotify_id, title, artist, energy, valence, emotion_label}
 *   segments      {Array}    arc.segments — [{emotion, track_count, tracks[]}]
 *   arcPath       {string[]} ordered emotion label sequence
 *   playingIndex  {number|null} currently playing flat track index
 *   onTrackClick  {fn}       called with (flatIndex) when a dot is clicked
 */

import * as d3 from 'd3'
import { useEffect, useRef, useState } from 'react'

// ── Emotion colour palette (mirrors Dashboard.jsx) ────────────────────────────
const EMOTION_COLORS = {
  energetic:   '#f59e0b', happy:       '#10b981', euphoric:    '#8b5cf6',
  peaceful:    '#06b6d4', focused:     '#3b82f6', romantic:    '#ec4899',
  nostalgic:   '#f97316', neutral:     '#6b7280', melancholic: '#6366f1',
  sad:         '#94a3b8', tense:       '#ef4444', angry:       '#dc2626',
}

const ec = (emotion) => EMOTION_COLORS[emotion] ?? '#8b5cf6'

// ── Chart constants ───────────────────────────────────────────────────────────
const H    = 160   // total SVG height
const PAD  = { top: 22, bottom: 28, left: 36, right: 16 }

export default function ArcVisualizer({
  tracks = [],
  segments = [],
  arcPath = [],
  playingIndex = null,
  onTrackClick,
}) {
  const containerRef = useRef(null)
  const svgRef       = useRef(null)
  const xScaleRef    = useRef(null)   // stable ref for playhead updater + tooltip
  const [width, setWidth]   = useState(680)
  const [tooltip, setTooltip] = useState(null)  // {x, y, track, index} | null

  // ── Responsive width ────────────────────────────────────────────────────────
  useEffect(() => {
    if (!containerRef.current) return
    const ro = new ResizeObserver(([entry]) => {
      setWidth(Math.floor(entry.contentRect.width))
    })
    ro.observe(containerRef.current)
    return () => ro.disconnect()
  }, [])

  // ── Main D3 render ──────────────────────────────────────────────────────────
  useEffect(() => {
    if (!tracks.length || !svgRef.current || width < 100) return

    const svg    = d3.select(svgRef.current)
    svg.selectAll('*').remove()

    const innerW = width  - PAD.left - PAD.right
    const innerH = H      - PAD.top  - PAD.bottom
    const n      = tracks.length

    // ── Scales ────────────────────────────────────────────────────────────────
    const xScale = d3.scaleLinear().domain([0, Math.max(n - 1, 1)]).range([0, innerW])
    const yScale = d3.scaleLinear().domain([0, 1]).range([innerH, 0])
    xScaleRef.current = xScale

    const g = svg.append('g').attr('transform', `translate(${PAD.left},${PAD.top})`)

    // ── Defs: clip, filters, gradients ────────────────────────────────────────
    const defs = svg.append('defs')

    // Glow filter for playing dot
    const glowFilter = defs.append('filter').attr('id', 'arc-glow').attr('x', '-50%').attr('y', '-50%').attr('width', '200%').attr('height', '200%')
    glowFilter.append('feGaussianBlur').attr('stdDeviation', '3').attr('result', 'blur')
    const feMerge = glowFilter.append('feMerge')
    feMerge.append('feMergeNode').attr('in', 'blur')
    feMerge.append('feMergeNode').attr('in', 'SourceGraphic')

    // Gradient for fill area
    const fillGrad = defs.append('linearGradient')
      .attr('id', 'arc-fill-grad').attr('x1', '0%').attr('y1', '0%').attr('x2', '0%').attr('y2', '100%')
    fillGrad.append('stop').attr('offset', '0%').attr('stop-color', 'rgba(139,92,246,0.22)')
    fillGrad.append('stop').attr('offset', '100%').attr('stop-color', 'rgba(139,92,246,0)')

    // Gradient for energy line (multi-stop from arcPath emotions)
    const lineGrad = defs.append('linearGradient')
      .attr('id', 'arc-line-grad').attr('x1', '0%').attr('y1', '0%').attr('x2', '100%').attr('y2', '0%')
    const pathLen = Math.max(arcPath.length - 1, 1)
    arcPath.forEach((emotion, i) => {
      lineGrad.append('stop')
        .attr('offset', `${(i / pathLen) * 100}%`)
        .attr('stop-color', ec(emotion))
    })

    // ── Segment bands ─────────────────────────────────────────────────────────
    let trackCursor = 0
    segments.forEach((seg) => {
      const start = trackCursor
      const end   = trackCursor + seg.track_count - 1
      trackCursor += seg.track_count

      if (start >= n) return
      const x1 = xScale(start)
      const x2 = xScale(Math.min(end, n - 1))
      const color = ec(seg.emotion)

      g.append('rect')
        .attr('x', x1).attr('y', 0)
        .attr('width', x2 - x1).attr('height', innerH)
        .attr('fill', color).attr('opacity', 0.07)

      // Segment label at top
      g.append('text')
        .attr('x', x1 + (x2 - x1) / 2).attr('y', -6)
        .attr('text-anchor', 'middle')
        .attr('font-size', 9).attr('font-family', 'DM Sans, sans-serif')
        .attr('fill', color).attr('opacity', 0.8)
        .text(seg.emotion)

      // Segment boundary line (except first)
      if (start > 0) {
        g.append('line')
          .attr('x1', x1).attr('y1', 0).attr('x2', x1).attr('y2', innerH)
          .attr('stroke', color).attr('stroke-width', 0.5).attr('opacity', 0.25)
      }
    })

    // ── Y-axis guide lines ────────────────────────────────────────────────────
    [0.25, 0.5, 0.75].forEach(v => {
      g.append('line')
        .attr('x1', 0).attr('y1', yScale(v)).attr('x2', innerW).attr('y2', yScale(v))
        .attr('stroke', 'rgba(255,255,255,0.06)').attr('stroke-width', 1)
    })

    // ── Y-axis labels ─────────────────────────────────────────────────────────
    const axisStyle = { fontSize: 9, fontFamily: 'DM Sans, sans-serif', fill: 'rgba(255,255,255,0.3)' }
    g.append('text').attr('x', -4).attr('y', 2).attr('text-anchor', 'end').attr('dominant-baseline', 'hanging')
      .attr('font-size', axisStyle.fontSize).attr('font-family', axisStyle.fontFamily).attr('fill', axisStyle.fill)
      .text('hi')
    g.append('text').attr('x', -4).attr('y', innerH).attr('text-anchor', 'end').attr('dominant-baseline', 'auto')
      .attr('font-size', axisStyle.fontSize).attr('font-family', axisStyle.fontFamily).attr('fill', axisStyle.fill)
      .text('lo')

    // ── Curve generators ──────────────────────────────────────────────────────
    const curve = d3.curveCatmullRom.alpha(0.5)

    const areaGen = d3.area()
      .x((_, i) => xScale(i))
      .y0(innerH)
      .y1(d => yScale(d.energy))
      .curve(curve)

    const lineGen = d3.line()
      .x((_, i) => xScale(i))
      .y(d => yScale(d.energy))
      .curve(curve)

    const valenceLineGen = d3.line()
      .x((_, i) => xScale(i))
      .y(d => yScale(d.valence ?? d.energy))
      .curve(curve)

    // ── Fill area ─────────────────────────────────────────────────────────────
    g.append('path')
      .datum(tracks)
      .attr('d', areaGen)
      .attr('fill', 'url(#arc-fill-grad)')

    // ── Valence line (dashed, secondary) ──────────────────────────────────────
    g.append('path')
      .datum(tracks)
      .attr('d', valenceLineGen)
      .attr('fill', 'none')
      .attr('stroke', 'rgba(148,163,184,0.35)')
      .attr('stroke-width', 1.5)
      .attr('stroke-dasharray', '3,4')

    // ── Energy line — animated draw-in ────────────────────────────────────────
    const energyPath = g.append('path')
      .datum(tracks)
      .attr('d', lineGen)
      .attr('fill', 'none')
      .attr('stroke', 'url(#arc-line-grad)')
      .attr('stroke-width', 2.5)
      .attr('stroke-linecap', 'round')

    const totalLen = energyPath.node().getTotalLength()
    energyPath
      .attr('stroke-dasharray', totalLen)
      .attr('stroke-dashoffset', totalLen)
      .transition()
      .duration(1200)
      .ease(d3.easeQuadInOut)
      .attr('stroke-dashoffset', 0)

    // ── Track dots ────────────────────────────────────────────────────────────
    g.selectAll('.track-dot')
      .data(tracks)
      .enter()
      .append('circle')
      .attr('class', 'track-dot')
      .attr('cx', (_, i) => xScale(i))
      .attr('cy', d => yScale(d.energy))
      .attr('r', 3.5)
      .attr('fill', d => ec(d.emotion_label))
      .attr('opacity', 0.85)
      .attr('cursor', onTrackClick ? 'pointer' : 'default')
      .on('click', (_, d) => {
        const idx = tracks.indexOf(d)
        if (idx !== -1) onTrackClick?.(idx)
      })

    // ── Playing indicator (initial) ───────────────────────────────────────────
    const pIdx   = playingIndex != null && playingIndex < n ? playingIndex : null
    const pColor = pIdx != null ? ec(tracks[pIdx]?.emotion_label) : '#8b5cf6'
    const pX     = pIdx != null ? xScale(pIdx) : -999
    const pY     = pIdx != null ? yScale(tracks[pIdx]?.energy ?? 0.5) : innerH / 2

    g.append('line')
      .attr('class', 'playing-line')
      .attr('x1', pX).attr('y1', 0).attr('x2', pX).attr('y2', innerH)
      .attr('stroke', pColor).attr('stroke-width', 1)
      .attr('opacity', pIdx != null ? 0.5 : 0)

    g.append('circle')
      .attr('class', 'playing-dot')
      .attr('cx', pX).attr('cy', pY).attr('r', 7)
      .attr('fill', pColor)
      .attr('filter', 'url(#arc-glow)')
      .attr('opacity', pIdx != null ? 1 : 0)

    // ── Mouse interaction: tooltip via nearest dot ────────────────────────────
    const overlay = g.append('rect')
      .attr('width', innerW).attr('height', innerH)
      .attr('fill', 'transparent')
      .attr('cursor', 'crosshair')

    overlay.on('mousemove', function (event) {
      const [mx] = d3.pointer(event)
      const idx  = Math.round(xScale.invert(mx))
      const clamped = Math.max(0, Math.min(n - 1, idx))
      const rect = containerRef.current.getBoundingClientRect()
      const svgRect = svgRef.current.getBoundingClientRect()

      setTooltip({
        x: PAD.left + xScale(clamped),
        y: PAD.top  + yScale(tracks[clamped].energy) - 12,
        track: tracks[clamped],
        index: clamped,
      })
    })
    overlay.on('mouseleave', () => setTooltip(null))
    overlay.on('click', function (event) {
      const [mx] = d3.pointer(event)
      const idx  = Math.round(xScale.invert(mx))
      const clamped = Math.max(0, Math.min(n - 1, idx))
      onTrackClick?.(clamped)
    })

  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tracks, segments, arcPath, width])

  // ── Playhead-only update (no full redraw) ───────────────────────────────────
  useEffect(() => {
    if (!svgRef.current || !xScaleRef.current || !tracks.length) return
    const xScale = xScaleRef.current
    const n      = tracks.length
    const innerH = H - PAD.top - PAD.bottom
    const yScale = d3.scaleLinear().domain([0, 1]).range([innerH, 0])

    const pIdx   = playingIndex != null && playingIndex < n ? playingIndex : null
    const pColor = pIdx != null ? ec(tracks[pIdx]?.emotion_label) : '#8b5cf6'
    const pX     = pIdx != null ? xScale(pIdx) : -999
    const pY     = pIdx != null ? yScale(tracks[pIdx]?.energy ?? 0.5) : innerH / 2

    const g = d3.select(svgRef.current).select('g')

    g.select('.playing-line')
      .transition().duration(300).ease(d3.easeLinear)
      .attr('x1', pX).attr('x2', pX)
      .attr('stroke', pColor)
      .attr('opacity', pIdx != null ? 0.5 : 0)

    g.select('.playing-dot')
      .transition().duration(300).ease(d3.easeLinear)
      .attr('cx', pX).attr('cy', pY)
      .attr('fill', pColor)
      .attr('opacity', pIdx != null ? 1 : 0)

  }, [playingIndex, tracks])

  // ── Render ──────────────────────────────────────────────────────────────────
  return (
    <div
      ref={containerRef}
      style={{ position: 'relative', width: '100%', userSelect: 'none' }}
    >
      {/* Legend */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 6 }}>
        <span style={{ color: 'rgba(255,255,255,0.35)', fontSize: 11, fontFamily: 'DM Sans, sans-serif' }}>
          Energy arc
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 5, color: 'rgba(148,163,184,0.55)', fontSize: 10, fontFamily: 'DM Sans, sans-serif' }}>
          <svg width="20" height="6"><line x1="0" y1="3" x2="20" y2="3" stroke="rgba(148,163,184,0.45)" strokeWidth="1.5" strokeDasharray="3,4"/></svg>
          valence
        </span>
      </div>

      <svg
        ref={svgRef}
        width={width}
        height={H}
        style={{ display: 'block', overflow: 'visible' }}
      />

      {/* Tooltip */}
      {tooltip && (
        <div style={{
          position: 'absolute',
          left: Math.min(tooltip.x, width - 170),
          top: Math.max(0, tooltip.y - 60),
          background: 'rgba(10,6,20,0.95)',
          border: `1px solid ${ec(tooltip.track.emotion_label)}55`,
          borderRadius: 8,
          padding: '8px 12px',
          pointerEvents: 'none',
          zIndex: 10,
          minWidth: 160,
          boxShadow: `0 4px 20px rgba(0,0,0,0.5)`,
        }}>
          <div style={{
            color: '#e2e8f0', fontSize: 12, fontWeight: 600,
            fontFamily: 'DM Sans, sans-serif',
            whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 140,
          }}>
            {tooltip.track.title}
          </div>
          <div style={{ color: '#94a3b8', fontSize: 11, fontFamily: 'DM Sans, sans-serif', marginTop: 2 }}>
            {tooltip.track.artist}
          </div>
          <div style={{ display: 'flex', gap: 8, marginTop: 6 }}>
            <span style={{
              background: `${ec(tooltip.track.emotion_label)}22`,
              color: ec(tooltip.track.emotion_label),
              fontSize: 10, padding: '2px 6px', borderRadius: 4,
              fontFamily: 'DM Sans, sans-serif',
            }}>
              {tooltip.track.emotion_label}
            </span>
            <span style={{ color: '#64748b', fontSize: 10, fontFamily: 'DM Sans, sans-serif' }}>
              E {Math.round((tooltip.track.energy ?? 0) * 100)}%
              · V {Math.round((tooltip.track.valence ?? 0) * 100)}%
            </span>
          </div>
          {onTrackClick && (
            <div style={{ color: '#475569', fontSize: 9, marginTop: 4, fontFamily: 'DM Sans, sans-serif' }}>
              click to play
            </div>
          )}
        </div>
      )}
    </div>
  )
}
