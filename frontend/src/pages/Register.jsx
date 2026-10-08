import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

export default function Register() {
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const { register } = useAuth()
  const navigate = useNavigate()

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    setSubmitting(true)
    try {
      await register(name, email, password)
      navigate('/')
    } catch (err) {
      setError(err.response?.data?.detail || 'Registration failed')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="auth-shell">
      <div className="auth-card">
        <div className="auth-brand">
          <span className="brand-mark" style={{ width: 52, height: 52, fontSize: 26 }}>S</span>
          <div>
            <h1>Create account</h1>
            <p>Get started with the Support Desk</p>
          </div>
        </div>

        {error && <div className="error-text">{error}</div>}

        <form onSubmit={handleSubmit}>
          <div className="auth-field">
            <label>Full name</label>
            <input type="text" value={name} onChange={(e) => setName(e.target.value)} required />
          </div>
          <div className="auth-field">
            <label>Email</label>
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </div>
          <div className="auth-field">
            <label>Password</label>
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
          </div>
          <button type="submit" style={{ width: '100%', justifyContent: 'center', padding: 12 }} disabled={submitting}>
            {submitting ? 'Creating…' : 'Create account'}
          </button>
        </form>

        <p className="hint" style={{ textAlign: 'center', marginTop: 18 }}>
          Already have an account? <Link to="/login">Sign in</Link>
        </p>
      </div>
    </div>
  )
}
