import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../api/client'
import { StatusBadge } from '../components/Badges'
import Avatar from '../components/Avatar'
import LiveDot from '../components/LiveDot'
import useWebSocket from '../hooks/useWebSocket'

const ACTIVE_STATUSES = ['open', 'in_progress']

export default function AdminMonitor() {
  const navigate = useNavigate()
  const [tickets, setTickets] = useState([])
  const [loading, setLoading] = useState(true)
  const [lastMessages, setLastMessages] = useState({}) // ticket_id -> { body, author_name, created_at }
  const [agentAvailability, setAgentAvailability] = useState({}) // agent_id -> availability
  const [flashId, setFlashId] = useState(null)
  const [live, setLive] = useState(false)

  useEffect(() => {
    async function load() {
      setLoading(true)
      const [ticketsRes, agentsRes] = await Promise.all([api.get('/tickets'), api.get('/agents')])
      setTickets(ticketsRes.data)
      const avail = {}
      agentsRes.data.forEach((a) => { avail[a.id] = a.availability })
      setAgentAvailability(avail)
      setLoading(false)
    }
    load()
  }, [])

  function flash(ticketId) {
    setFlashId(ticketId)
    setTimeout(() => setFlashId((cur) => (cur === ticketId ? null : cur)), 900)
  }

  function handleWsMessage(event) {
    if (event.type === 'ticket.created') {
      setTickets((prev) => [event.data, ...prev.filter((t) => t.id !== event.data.id)])
      flash(event.data.id)
    } else if (event.type === 'ticket.updated') {
      setTickets((prev) => prev.map((t) => (t.id === event.data.id ? { ...t, ...event.data } : t)))
      flash(event.data.id)
    } else if (event.type === 'comment.created') {
      setLastMessages((prev) => ({
        ...prev,
        [event.data.ticket_id]: {
          body: event.data.body,
          author_name: event.data.author_name,
          created_at: event.data.created_at,
        },
      }))
      setTickets((prev) =>
        prev.map((t) => (t.id === event.data.ticket_id ? { ...t, updated_at: event.data.created_at } : t))
      )
      flash(event.data.ticket_id)
    } else if (event.type === 'agent.availability_changed') {
      setAgentAvailability((prev) => ({ ...prev, [event.data.agent_id]: event.data.availability }))
    } else if (event.type === 'sla.breached') {
      flash(event.data.ticket_id)
    }
  }

  useWebSocket('/ws/admin', handleWsMessage, true, setLive)

  const active = useMemo(
    () =>
      tickets
        .filter((t) => ACTIVE_STATUSES.includes(t.status))
        .sort((a, b) => new Date(b.updated_at) - new Date(a.updated_at)),
    [tickets]
  )

  return (
    <div>
      <div className="between" style={{ marginBottom: 20 }}>
        <div>
          <div className="h-title">Live Conversations</div>
          <div className="h-sub">
            {active.length} active ticket{active.length === 1 ? '' : 's'} · watch every conversation and reassign in real time
          </div>
        </div>
        <LiveDot connected={live} />
      </div>

      <div className="card tbl-wrap">
        {loading ? (
          <div className="loading-state"><span className="spinner" /> Loading conversations…</div>
        ) : active.length === 0 ? (
          <div className="empty">
            <div className="ei">
              <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
                <circle cx="12" cy="12" r="3" /><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7-10-7-10-7z" />
              </svg>
            </div>
            <h3>No active conversations right now.</h3>
          </div>
        ) : (
          active.map((t) => {
            const preview = lastMessages[t.id]
            const availability = t.assigned_agent_id ? agentAvailability[t.assigned_agent_id] : null
            return (
              <div
                key={t.id}
                className={`monitor-row${flashId === t.id ? ' monitor-flash' : ''}`}
                onClick={() => navigate(`/tickets/${t.id}`)}
              >
                <Avatar name={t.customer_name} size={34} />
                <div className="mr-main">
                  <div className="mr-subj">#{t.id} {t.subject}</div>
                  <div className="mr-preview">
                    {preview ? `${preview.author_name}: ${preview.body}` : t.description}
                  </div>
                </div>
                <StatusBadge status={t.status} />
                <div className="mr-agent">
                  {t.assigned_agent_name ? (
                    <>
                      {availability && <span className={`avail-dot ${availability}`} />}
                      {t.assigned_agent_name}
                    </>
                  ) : t.handling_mode === 'ai' ? (
                    <span className="hint-text">🤖 AI handling</span>
                  ) : (
                    <span className="hint-text">Unassigned</span>
                  )}
                </div>
                <div className="mr-time">
                  {new Date(t.updated_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                </div>
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}
