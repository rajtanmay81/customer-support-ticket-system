import { NavLink, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import Avatar from './Avatar'

const AVAILABILITY_OPTIONS = ['online', 'busy', 'offline']

export default function Sidebar({ counts }) {
  const { user, logout, isStaff, isAdmin, setAvailability } = useAuth()
  const navigate = useNavigate()

  function handleLogout() {
    logout()
    navigate('/login')
  }

  return (
    <aside className="rail">
      <div className="brand">
        <span className="brand-mark">S</span>
        <div>
          <div className="name">Support Desk</div>
          <div className="sub">Ticketing · ML · GenAI</div>
        </div>
      </div>

      <div className="nav-label">Workspace</div>
      <NavLink to="/" end className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}>
        <svg className="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01" />
        </svg>
        <span>{isAdmin ? 'All Tickets' : 'My Tickets'}</span>
        {counts?.total != null && <span className="count">{counts.total}</span>}
      </NavLink>

      {isStaff && (
        <NavLink to="/?sla=breach" className="nav-item alert">
          <svg className="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
            <path d="M12 9v4M12 17h.01" />
          </svg>
          SLA Breaches
          {counts?.breach != null && <span className="count">{counts.breach}</span>}
        </NavLink>
      )}

      {!isStaff && (
        <NavLink to="/new" className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}>
          <svg className="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M12 5v14M5 12h14" />
          </svg>
          New Ticket
        </NavLink>
      )}

      {isAdmin && (
        <NavLink to="/admin/monitor" className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}>
          <svg className="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="3" /><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7-10-7-10-7z" />
          </svg>
          Live Conversations
        </NavLink>
      )}

      {isAdmin && (
        <NavLink to="/admin/users" className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}>
          <svg className="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75" />
          </svg>
          Manage Users
        </NavLink>
      )}

      {isAdmin && (
        <NavLink to="/admin/analytics" className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}>
          <svg className="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M3 3v18h18M7 15l4-5 3 3 5-7" />
          </svg>
          Analytics
        </NavLink>
      )}

      {isAdmin && (
        <NavLink to="/admin/ml-feedback" className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}>
          <svg className="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="m12 3 1.9 5.8L20 10l-6.1 1.2L12 17l-1.9-5.8L4 10l6.1-1.2z" />
          </svg>
          Model Feedback
        </NavLink>
      )}

      <div className="rail-foot">
        {isStaff && (
          <>
            <div className="nav-label" style={{ padding: '0 10px 6px' }}>My availability</div>
            <div className="avail-toggle">
              {AVAILABILITY_OPTIONS.map((opt) => (
                <button
                  key={opt}
                  type="button"
                  className={`avail-btn${user.availability === opt ? ` on ${opt}` : ''}`}
                  onClick={() => setAvailability(opt)}
                >
                  {opt}
                </button>
              ))}
            </div>
          </>
        )}
        <div className="userchip" onClick={handleLogout} title="Log out">
          <Avatar name={user.name} size={32} />
          <div>
            <div className="nm">{user.name}</div>
            <div className="rl">{user.role}</div>
          </div>
          <svg className="out" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16">
            <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9" />
          </svg>
        </div>
      </div>
    </aside>
  )
}
