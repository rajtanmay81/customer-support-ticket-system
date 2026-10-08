import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import api from '../api/client'

export default function ResetPassword() {
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token') || ''

  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [done, setDone] = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    if (password !== confirmPassword) {
      setError('Passwords do not match')
      return
    }
    setSubmitting(true)
    try {
      await api.post('/auth/reset-password', { token, new_password: password })
      setDone(true)
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not reset password')
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
            <h1>Reset password</h1>
            <p>Choose a new password for your account</p>
          </div>
        </div>

        {error && <div className="error-text">{error}</div>}

        {done ? (
          <div className="notice info">
            Password has been reset. <Link to="/login">Sign in</Link>.
          </div>
        ) : !token ? (
          <div className="error-text">This reset link is missing its token — please request a new one.</div>
        ) : (
          <form onSubmit={handleSubmit}>
            <div className="auth-field">
              <label>New password</label>
              <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
            </div>
            <div className="auth-field">
              <label>Confirm password</label>
              <input type="password" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} required />
            </div>
            <button type="submit" style={{ width: '100%', justifyContent: 'center', padding: 12 }} disabled={submitting}>
              {submitting ? 'Resetting…' : 'Reset password'}
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
