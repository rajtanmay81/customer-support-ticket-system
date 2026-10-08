import { useState } from 'react'
import { Link } from 'react-router-dom'
import api from '../api/client'

export default function ForgotPassword() {
  const [email, setEmail] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [sent, setSent] = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    setSubmitting(true)
    try {
      await api.post('/auth/forgot-password', { email })
      setSent(true)
    } catch (err) {
      setError(err.response?.data?.detail || 'Something went wrong')
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
            <h1>Forgot password</h1>
            <p>We'll send a reset link to your email</p>
          </div>
        </div>

        {error && <div className="error-text">{error}</div>}

        {sent ? (
          <div className="notice info">
            If that email is registered, a password reset link has been sent.
          </div>
        ) : (
          <form onSubmit={handleSubmit}>
            <div className="auth-field">
              <label>Email</label>
              <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
            </div>
            <button type="submit" style={{ width: '100%', justifyContent: 'center', padding: 12 }} disabled={submitting}>
              {submitting ? 'Sending…' : 'Send reset link'}
            </button>
          </form>
        )}

        <p className="hint" style={{ textAlign: 'center', marginTop: 18 }}>
          <Link to="/login">Back to sign in</Link>
        </p>
      </div>
    </div>
  )
}
