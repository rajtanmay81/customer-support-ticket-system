import { useEffect, useState } from 'react'
import api from '../api/client'
import { useAuth } from '../context/AuthContext'
import Avatar from '../components/Avatar'

const STAFF_ROLES = ['agent', 'admin']

export default function AdminUsers() {
  const { user: me } = useAuth()
  const [users, setUsers] = useState([])
  const [loading, setLoading] = useState(true)
  const [form, setForm] = useState({ name: '', email: '', password: '', role: 'agent' })
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState('')

  async function load() {
    setLoading(true)
    const res = await api.get('/admin/users')
    setUsers(res.data)
    setLoading(false)
  }

  useEffect(() => { load() }, [])

  async function handleCreate(e) {
    e.preventDefault()
    setError('')
    setCreating(true)
    try {
      await api.post('/admin/users', form)
      setForm({ name: '', email: '', password: '', role: 'agent' })
      await load()
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not create user')
    } finally {
      setCreating(false)
    }
  }

  async function handleUpdate(id, patch) {
    setError('')
    try {
      await api.patch(`/admin/users/${id}`, patch)
      await load()
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not update user')
    }
  }

  return (
    <div>
      <div className="crumbs" style={{ marginBottom: 8 }}>Admin / <b>Users</b></div>
      <div className="h-title" style={{ marginBottom: 4 }}>Manage users</div>
      <div className="h-sub" style={{ marginBottom: 22 }}>
        Create and manage agent and admin accounts. Customers self-register from the login page.
      </div>

      {error && <div className="error-text" style={{ marginBottom: 16 }}>{error}</div>}

      <div className="card card-pad" style={{ marginBottom: 20 }}>
        <div className="side-h">New staff account</div>
        <form onSubmit={handleCreate}>
          <div className="row" style={{ gap: 12, alignItems: 'flex-start', flexWrap: 'wrap' }}>
            <div style={{ flex: '1 1 180px' }}>
              <label>Full name</label>
              <input
                type="text"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                required
              />
            </div>
            <div style={{ flex: '1 1 220px' }}>
              <label>Email</label>
              <input
                type="email"
                value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })}
                required
              />
            </div>
            <div style={{ flex: '1 1 160px' }}>
              <label>Password</label>
              <input
                type="password"
                value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })}
                required
              />
            </div>
            <div style={{ flex: '0 1 140px' }}>
              <label>Role</label>
              <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
                {STAFF_ROLES.map((r) => <option key={r} value={r}>{r.charAt(0).toUpperCase() + r.slice(1)}</option>)}
              </select>
            </div>
          </div>
          <div className="row" style={{ justifyContent: 'flex-end', marginTop: 4 }}>
            <button type="submit" disabled={creating}>{creating ? 'Creating…' : 'Create account'}</button>
          </div>
        </form>
      </div>

      <div className="card tbl-wrap">
        {loading ? (
          <div className="loading-state"><span className="spinner" /> Loading users…</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>User</th>
                <th>Email</th>
                <th>Role</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => {
                const isSelf = u.id === me.id
                const isCustomer = u.role === 'customer'
                return (
                  <tr key={u.id}>
                    <td>
                      <div className="cell-user"><Avatar name={u.name} size={24} />{u.name}</div>
                    </td>
                    <td>{u.email}</td>
                    <td>
                      {isCustomer ? (
                        <span className="hint-text">customer</span>
                      ) : (
                        <select
                          value={u.role}
                          disabled={isSelf}
                          title={isSelf ? "You can't change your own role" : undefined}
                          onChange={(e) => handleUpdate(u.id, { role: e.target.value })}
                        >
                          {STAFF_ROLES.map((r) => <option key={r} value={r}>{r.charAt(0).toUpperCase() + r.slice(1)}</option>)}
                        </select>
                      )}
                    </td>
                    <td>
                      <span className={`badge ${u.is_active ? 'status-resolved' : 'status-closed'}`}>
                        {u.is_active ? 'active' : 'inactive'}
                      </span>
                    </td>
                    <td>
                      {!isCustomer && (
                        <button
                          type="button"
                          className="ghost btn-sm"
                          disabled={isSelf}
                          title={isSelf ? "You can't deactivate your own account" : undefined}
                          onClick={() => handleUpdate(u.id, { is_active: !u.is_active })}
                        >
                          {u.is_active ? 'Deactivate' : 'Activate'}
                        </button>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
