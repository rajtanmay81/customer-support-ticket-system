import { useCallback, useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import api from '../api/client'
import { useAuth } from '../context/AuthContext'
import useWebSocket from '../hooks/useWebSocket'
import Sidebar from './Sidebar'

function crumbFor(pathname, isAdmin) {
  if (pathname === '/') return { section: 'Workspace', page: isAdmin ? 'All Tickets' : 'My Tickets' }
  if (pathname === '/new') return { section: 'Tickets', page: 'New' }
  if (pathname === '/admin/users') return { section: 'Admin', page: 'Users' }
  if (pathname === '/admin/monitor') return { section: 'Admin', page: 'Live Conversations' }
  if (pathname === '/admin/analytics') return { section: 'Admin', page: 'Analytics' }
  if (pathname === '/admin/ml-feedback') return { section: 'Admin', page: 'Model Feedback' }
  const m = pathname.match(/^\/tickets\/(\d+)/)
  if (m) return { section: 'Tickets', page: `#${m[1]}` }
  return { section: 'Workspace', page: '' }
}

export default function AppShell({ children }) {
  const { isAdmin } = useAuth()
  const location = useLocation()
  const navigate = useNavigate()
  const [counts, setCounts] = useState({ total: null, breach: null })
  const [breachToasts, setBreachToasts] = useState([])

  const refreshCounts = useCallback(() => {
    api.get('/tickets').then((res) => {
      const tickets = res.data
      const breach = tickets.filter((t) => t.sla && (t.sla.response_breached || t.sla.resolution_breached)).length
      setCounts({ total: tickets.length, breach })
    })
  }, [])

  useEffect(() => {
    refreshCounts()
  }, [location.pathname, refreshCounts])

  function dismissToast(toastId) {
    setBreachToasts((prev) => prev.filter((t) => t.id !== toastId))
  }

  // Site-wide, not just on /admin/monitor — a breach on a ticket nobody happens to be
  // looking at is exactly the case proactive notification (main.py's background sweep)
  // exists for. Pushed to every admin session regardless of which page is open.
  function handleAdminWsMessage(event) {
    if (event.type !== 'sla.breached') return
    refreshCounts()
    const toastId = `${event.data.ticket_id}-${event.data.breach_type}-${Date.now()}`
    setBreachToasts((prev) => [...prev, { id: toastId, ...event.data }])
    setTimeout(() => dismissToast(toastId), 8000)
  }

  useWebSocket('/ws/admin', handleAdminWsMessage, isAdmin)

  const crumb = crumbFor(location.pathname, isAdmin)

  return (
    <div className="app">
      <Sidebar counts={counts} />
      <div className="main">
        <div className="topbar">
          <div className="crumbs">
            {crumb.section} / <b>{crumb.page}</b>
          </div>
        </div>
        <div className="page">{children}</div>
      </div>

      {breachToasts.length > 0 && (
        <div className="toast-stack">
          {breachToasts.map((t) => (
            <div
              key={t.id}
              className="toast toast-breach"
              onClick={() => { navigate(`/tickets/${t.ticket_id}`); dismissToast(t.id) }}
            >
              <span aria-hidden="true">🔴</span>
              <div className="toast-body">
                <div className="toast-title">SLA {t.breach_type === 'response' ? 'first response' : 'resolution'} breached</div>
                <div className="toast-sub">#{t.ticket_id} {t.subject}</div>
              </div>
              <button
                type="button"
                className="toast-close"
                onClick={(e) => { e.stopPropagation(); dismissToast(t.id) }}
                aria-label="Dismiss"
              >
                ×
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
