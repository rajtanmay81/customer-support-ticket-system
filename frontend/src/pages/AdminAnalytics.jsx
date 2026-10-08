import { useEffect, useMemo, useState } from 'react'
import api from '../api/client'

const CHART_W = 560
const BAR_THICK = 22
const BAR_GAP = 14

// Sentiment/SLA colors are status tokens (reserved meaning, not a categorical
// palette) — always paired with an icon + label below, never color alone.
const SENTIMENT_META = {
  angry: { label: 'Angry', icon: '😠', color: 'var(--danger)' },
  frustrated: { label: 'Frustrated', icon: '😕', color: 'var(--warn)' },
  neutral: { label: 'Neutral', icon: '😐', color: 'var(--ink-3)' },
  satisfied: { label: 'Satisfied', icon: '🙂', color: 'var(--ok)' },
}
const SENTIMENT_ORDER = ['angry', 'frustrated', 'neutral', 'satisfied']

function niceMax(value) {
  if (value <= 0) return 1
  const magnitude = 10 ** Math.floor(Math.log10(value))
  const steps = [1, 2, 5, 10]
  for (const step of steps) {
    if (value <= step * magnitude) return step * magnitude
  }
  return 10 * magnitude
}

function EmptyChart({ label }) {
  return <p className="hint-text" style={{ padding: '20px 0' }}>{label}</p>
}

// Single-series line + area over time — sequential job, one hue (primary).
function VolumeChart({ data }) {
  if (data.length === 0) return <EmptyChart label="No tickets in the last 30 days." />

  const height = 160
  const padL = 34
  const padB = 20
  const w = CHART_W - padL
  const max = niceMax(Math.max(...data.map((d) => d.count)))
  const stepX = data.length > 1 ? w / (data.length - 1) : 0
  const yFor = (v) => height - padB - (v / max) * (height - padB - 10)
  const points = data.map((d, i) => [padL + i * stepX, yFor(d.count)])
  const linePath = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p[0]} ${p[1]}`).join(' ')
  const areaPath = `${linePath} L ${points[points.length - 1][0]} ${height - padB} L ${points[0][0]} ${height - padB} Z`
  const last = points[points.length - 1]
  const gridTicks = [0, 0.5, 1]

  return (
    <svg viewBox={`0 0 ${CHART_W} ${height}`} width="100%" height={height} role="img" aria-label="Daily ticket volume, last 30 days">
      {gridTicks.map((t) => (
        <g key={t}>
          <line x1={padL} x2={CHART_W} y1={yFor(max * t)} y2={yFor(max * t)} stroke="var(--border)" strokeWidth="1" />
          <text x={padL - 8} y={yFor(max * t) + 4} fontSize="10" fill="var(--ink-3)" textAnchor="end">
            {Math.round(max * t)}
          </text>
        </g>
      ))}
      <path d={areaPath} fill="var(--primary-wash)" stroke="none" />
      <path d={linePath} fill="none" stroke="var(--primary)" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={last[0]} cy={last[1]} r="4" fill="var(--primary)" stroke="var(--surface)" strokeWidth="2" />
      <text x={last[0]} y={last[1] - 10} fontSize="11" fontWeight="700" fill="var(--ink)" textAnchor="end">
        {data[data.length - 1].count}
      </text>
      <text x={padL} y={height} fontSize="10" fill="var(--ink-3)">{data[0].date.slice(5)}</text>
      <text x={CHART_W} y={height} fontSize="10" fill="var(--ink-3)" textAnchor="end">{data[data.length - 1].date.slice(5)}</text>
    </svg>
  )
}

// Nominal categories, single series → same hue for every bar (never color-by-value).
function CategoryBars({ data }) {
  if (data.length === 0) return <EmptyChart label="No categorized tickets yet." />
  const sorted = [...data].sort((a, b) => b.count - a.count)
  const max = Math.max(...sorted.map((d) => d.count))
  const labelW = 110
  const barW = CHART_W - labelW - 46
  const rowH = BAR_THICK + BAR_GAP
  const height = sorted.length * rowH

  return (
    <svg viewBox={`0 0 ${CHART_W} ${height}`} width="100%" height={height} role="img" aria-label="Tickets by category">
      {sorted.map((d, i) => {
        const w = Math.max((d.count / max) * barW, 2)
        const y = i * rowH
        return (
          <g key={d.category}>
            <text x={labelW - 10} y={y + BAR_THICK / 2 + 4} fontSize="11.5" fill="var(--ink-2)" textAnchor="end">
              {d.category.replace('_', ' ')}
            </text>
            <rect x={labelW} y={y} width={w} height={BAR_THICK} rx="4" fill="var(--primary)" />
            <text x={labelW + w + 8} y={y + BAR_THICK / 2 + 4} fontSize="11.5" fontWeight="700" fill="var(--ink)">
              {d.count}
            </text>
          </g>
        )
      })}
    </svg>
  )
}

function SentimentBars({ data }) {
  const byKey = Object.fromEntries(data.map((d) => [d.sentiment, d.count]))
  const total = data.reduce((sum, d) => sum + d.count, 0)
  if (total === 0) return <EmptyChart label="No sentiment recorded yet (only tracked during AI-first triage)." />

  const max = Math.max(...SENTIMENT_ORDER.map((k) => byKey[k] || 0))
  const labelW = 110
  const barW = CHART_W - labelW - 46
  const rowH = BAR_THICK + BAR_GAP
  const height = SENTIMENT_ORDER.length * rowH

  return (
    <svg viewBox={`0 0 ${CHART_W} ${height}`} width="100%" height={height} role="img" aria-label="Customer sentiment breakdown">
      {SENTIMENT_ORDER.map((key, i) => {
        const count = byKey[key] || 0
        const meta = SENTIMENT_META[key]
        const w = max > 0 ? Math.max((count / max) * barW, count > 0 ? 2 : 0) : 0
        const y = i * rowH
        return (
          <g key={key}>
            <text x={labelW - 10} y={y + BAR_THICK / 2 + 4} fontSize="11.5" fill="var(--ink-2)" textAnchor="end">
              {meta.icon} {meta.label}
            </text>
            <rect x={labelW} y={y} width={barW} height={BAR_THICK} rx="4" fill="var(--surface-2)" />
            {w > 0 && <rect x={labelW} y={y} width={w} height={BAR_THICK} rx="4" fill={meta.color} />}
            <text x={labelW + Math.max(w, 0) + 8} y={y + BAR_THICK / 2 + 4} fontSize="11.5" fontWeight="700" fill="var(--ink)">
              {count}
            </text>
          </g>
        )
      })}
    </svg>
  )
}

function SlaRow({ label, met, breached, y }) {
  const total = met + breached
  const labelW = 110
  const barW = CHART_W - labelW - 60
  const metW = total > 0 ? (met / total) * barW : 0
  const breachedW = total > 0 ? (breached / total) * barW : 0
  const gap = met > 0 && breached > 0 ? 2 : 0

  return (
    <g>
      <text x={labelW - 10} y={y + BAR_THICK / 2 + 4} fontSize="11.5" fill="var(--ink-2)" textAnchor="end">{label}</text>
      {total === 0 ? (
        <text x={labelW} y={y + BAR_THICK / 2 + 4} fontSize="11" fill="var(--ink-3)">No data yet</text>
      ) : (
        <>
          <rect x={labelW} y={y} width={Math.max(metW - gap / 2, 0)} height={BAR_THICK} rx="4" fill="var(--ok)" />
          <rect x={labelW + metW + gap / 2} y={y} width={Math.max(breachedW - gap / 2, 0)} height={BAR_THICK} rx="4" fill="var(--danger)" />
          <text x={labelW + barW + 10} y={y + BAR_THICK / 2 + 4} fontSize="11.5" fontWeight="700" fill="var(--ink)">
            {Math.round((met / total) * 100)}% met
          </text>
        </>
      )}
    </g>
  )
}

function SlaCompliance({ overview }) {
  const rowH = BAR_THICK + BAR_GAP
  const height = rowH * 2
  return (
    <>
      <svg viewBox={`0 0 ${CHART_W} ${height}`} width="100%" height={height} role="img" aria-label="SLA compliance">
        <SlaRow label="First response" met={overview.sla_response_met} breached={overview.sla_response_breached} y={0} />
        <SlaRow label="Resolution" met={overview.sla_resolution_met} breached={overview.sla_resolution_breached} y={rowH} />
      </svg>
      <div className="row" style={{ gap: 16, marginTop: 4 }}>
        <span className="hint-text"><span style={{ color: 'var(--ok)' }}>■</span> Met</span>
        <span className="hint-text"><span style={{ color: 'var(--danger)' }}>■</span> Breached</span>
      </div>
    </>
  )
}

export default function AdminAnalytics() {
  const [overview, setOverview] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get('/admin/analytics/overview').then((res) => {
      setOverview(res.data)
      setLoading(false)
    })
  }, [])

  const totalTickets = useMemo(
    () => overview?.ticket_volume.reduce((sum, d) => sum + d.count, 0) ?? 0,
    [overview]
  )

  if (loading) {
    return <div className="loading-state"><span className="spinner" /> Loading analytics…</div>
  }

  return (
    <div>
      <div className="crumbs" style={{ marginBottom: 8 }}>Admin / <b>Analytics</b></div>
      <div className="h-title" style={{ marginBottom: 4 }}>Analytics</div>
      <div className="h-sub" style={{ marginBottom: 22 }}>
        Sentiment, volume, SLA compliance, and category mix — aggregated from data already
        tracked elsewhere in the app.
      </div>

      <div className="row" style={{ gap: 16, marginBottom: 20, flexWrap: 'wrap' }}>
        <div className="card card-pad" style={{ flex: '1 1 160px' }}>
          <div className="hint-text">Tickets (last 30 days)</div>
          <div style={{ fontSize: 26, fontWeight: 700, marginTop: 4 }}>{totalTickets}</div>
        </div>
        <div className="card card-pad" style={{ flex: '1 1 160px' }}>
          <div className="hint-text">Average CSAT rating</div>
          <div style={{ fontSize: 26, fontWeight: 700, marginTop: 4 }}>
            {overview.average_rating != null ? `${overview.average_rating} ★` : '—'}
          </div>
          <div className="hint-text">{overview.rating_count} rating{overview.rating_count === 1 ? '' : 's'}</div>
        </div>
        <div className="card card-pad" style={{ flex: '1 1 160px' }}>
          <div className="hint-text">SLA compliance (response)</div>
          <div style={{ fontSize: 26, fontWeight: 700, marginTop: 4 }}>
            {overview.sla_response_met + overview.sla_response_breached > 0
              ? `${Math.round((overview.sla_response_met / (overview.sla_response_met + overview.sla_response_breached)) * 100)}%`
              : '—'}
          </div>
        </div>
      </div>

      <div className="row" style={{ gap: 16, flexWrap: 'wrap', alignItems: 'flex-start' }}>
        <div className="card card-pad" style={{ flex: '1 1 460px' }}>
          <div className="side-h">Ticket volume — last 30 days</div>
          <VolumeChart data={overview.ticket_volume} />
        </div>
        <div className="card card-pad" style={{ flex: '1 1 320px' }}>
          <div className="side-h">SLA compliance</div>
          <SlaCompliance overview={overview} />
        </div>
        <div className="card card-pad" style={{ flex: '1 1 320px' }}>
          <div className="side-h">Tickets by category</div>
          <CategoryBars data={overview.category_distribution} />
        </div>
        <div className="card card-pad" style={{ flex: '1 1 320px' }}>
          <div className="side-h">Customer sentiment (AI-detected)</div>
          <SentimentBars data={overview.sentiment_counts} />
        </div>
      </div>
    </div>
  )
}
