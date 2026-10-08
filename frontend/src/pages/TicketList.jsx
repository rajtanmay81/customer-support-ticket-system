import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import api from '../api/client'
import { useAuth } from '../context/AuthContext'
import { StatusBadge, PriorityBar, SLABadge } from '../components/Badges'
import Avatar from '../components/Avatar'
import LiveDot from '../components/LiveDot'
import useWebSocket from '../hooks/useWebSocket'
import { slaInfo } from '../utils/sla'

const STATUSES = ['open', 'in_progress', 'resolved', 'closed']
const STATUS_LABELS = { open: 'Open', in_progress: 'In progress', resolved: 'Resolved', closed: 'Closed' }

export default function TicketList() {
  const { user, isStaff, isAdmin } = useAuth()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const breachOnly = searchParams.get('sla') === 'breach'

  const [tickets, setTickets] = useState([])
  const [categories, setCategories] = useState([])
  const [priorities, setPriorities] = useState([])
  const [statusFilter, setStatusFilter] = useState('all')
  const [priority, setPriority] = useState('')
  const [category, setCategory] = useState('')
  const [assignedToMe, setAssignedToMe] = useState(false)
  const [loading, setLoading] = useState(true)

  async function loadTickets() {
    setLoading(true)
    const params = {}
    if (priority) params.priority = priority
    if (category) params.category = category
    if (assignedToMe) params.assigned_to_me = true
    const res = await api.get('/tickets', { params })
    setTickets(res.data)
    setLoading(false)
  }

  useEffect(() => {
    loadTickets()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [priority, category, assignedToMe])

  useEffect(() => {
    api.get('/categories').then((res) => setCategories(res.data))
    api.get('/priorities').then((res) => setPriorities(res.data))
  }, [])

  const [live, setLive] = useState(false)

  function handleWsMessage(event) {
    if (event.type === 'ticket.created') {
      setTickets((prev) => [event.data, ...prev.filter((t) => t.id !== event.data.id)])
    } else if (event.type === 'ticket.updated') {
      setTickets((prev) => prev.map((t) => (t.id === event.data.id ? { ...t, ...event.data } : t)))
    }
  }

  useWebSocket('/ws/admin', handleWsMessage, isAdmin, setLive)

  const byStatus = statusFilter === 'all' ? tickets : tickets.filter((t) => t.status === statusFilter)
  const visible = breachOnly ? byStatus.filter((t) => slaInfo(t)?.state === 'breach') : byStatus
  const breachCount = tickets.filter((t) => slaInfo(t)?.state === 'breach').length

  return (
    <div>
      <div className="between" style={{ marginBottom: 20 }}>
        <div>
          <div className="h-title">{isAdmin ? 'All Tickets' : 'My Tickets'}</div>
          <div className="h-sub">
            {tickets.length} ticket{tickets.length === 1 ? '' : 's'}
            {breachCount > 0 && ` · ${breachCount} breaching SLA`}
          </div>
        </div>
        <div className="row" style={{ gap: 14 }}>
          {isAdmin && <LiveDot connected={live} />}
          {!isStaff && (
            <button onClick={() => navigate('/new')}>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="15" height="15"><path d="M12 5v14M5 12h14" /></svg>
              New Ticket
            </button>
          )}
        </div>
      </div>

      {breachOnly && (
        <div className="notice info" style={{ marginBottom: 16 }}>
          Showing only tickets breaching their SLA.{' '}
          <Link to="/" onClick={() => setSearchParams({})}>Clear filter</Link>
        </div>
      )}

      <div className="toolbar">
        <button className={`chip${statusFilter === 'all' ? ' on' : ''}`} onClick={() => setStatusFilter('all')}>
          All <span className="n">{tickets.length}</span>
        </button>
        {STATUSES.map((s) => (
          <button key={s} className={`chip${statusFilter === s ? ' on' : ''}`} onClick={() => setStatusFilter(s)}>
            {STATUS_LABELS[s]} <span className="n">{tickets.filter((t) => t.status === s).length}</span>
          </button>
        ))}

        <div style={{ width: 1, height: 24, background: 'var(--border)', margin: '0 4px' }} />

        <div className="select">
          <select value={priority} onChange={(e) => setPriority(e.target.value)}>
            <option value="">All priorities</option>
            {priorities.map((p) => <option key={p.id} value={p.name}>{p.name.charAt(0).toUpperCase() + p.name.slice(1)}</option>)}
          </select>
        </div>
        <div className="select">
          <select value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="">All categories</option>
            {categories.map((c) => <option key={c.id} value={c.name}>{c.name.replace('_', ' ')}</option>)}
          </select>
        </div>

        {isAdmin && (
          <label className="chip" style={{ cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={assignedToMe}
              onChange={(e) => setAssignedToMe(e.target.checked)}
            />
            Assigned to me
          </label>
        )}
      </div>

      <div className="card tbl-wrap">
        {loading ? (
          <div className="loading-state"><span className="spinner" /> Loading tickets…</div>
        ) : visible.length === 0 ? (
          <div className="empty">
            <div className="ei">
              <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6"><path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01" /></svg>
            </div>
            <h3>{isAdmin ? 'No tickets match these filters.' : isStaff ? "You don't have any tickets assigned to you yet." : "You haven't raised any tickets yet."}</h3>
          </div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Ticket</th>
                {isStaff && <th>Customer</th>}
                <th>Category</th>
                <th>Priority</th>
                <th>Status</th>
                <th>SLA</th>
                {isStaff && <th>Agent</th>}
              </tr>
            </thead>
            <tbody>
              {visible.map((t) => (
                <tr key={t.id} className="clickable-row" onClick={() => navigate(`/tickets/${t.id}`)}>
                  <td>
                    <div className="tk-subj">{t.subject}</div>
                    <div className="tk-id">#{t.id}</div>
                  </td>
                  {isStaff && (
                    <td>
                      <div className="cell-user"><Avatar name={t.customer_name} size={24} />{t.customer_name}</div>
                    </td>
                  )}
                  <td>{t.category ? t.category.replace('_', ' ') : '—'}</td>
                  <td><PriorityBar priority={t.priority} /></td>
                  <td><StatusBadge status={t.status} /></td>
                  <td><SLABadge ticket={t} /></td>
                  {isStaff && (
                    <td>
                      {t.assigned_agent_name
                        ? <div className="cell-user"><Avatar name={t.assigned_agent_name} size={24} />{t.assigned_agent_name}</div>
                        : t.handling_mode === 'ai'
                          ? <span className="hint-text">🤖 AI handling</span>
                          : <span className="hint-text">Unassigned</span>}
                      {!isAdmin && t.assigned_agent_id !== user.id && (
                        <span className="assignment-tag admin" style={{ marginLeft: 6 }}>read-only</span>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
