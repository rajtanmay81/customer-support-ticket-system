import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import api from '../api/client'

export default function Login() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [signingIn, setSigningIn] = useState(false)
  const [demoAccounts, setDemoAccounts] = useState([])
  const { login } = useAuth()
  const navigate = useNavigate()

  useEffect(() => {
    api.get('/auth/demo-accounts')
      .then((res) => setDemoAccounts(res.data))
      .catch(() => setDemoAccounts([]))
  }, [])

  async function doLogin(loginEmail, loginPassword) {
    setError('')
    setSigningIn(true)
    try {
      await login(loginEmail, loginPassword)
      navigate('/')
    } catch (err) {
      setError(err.response?.data?.detail || 'Login failed')
    } finally {
      setSigningIn(false)
    }
  }

  function handleSubmit(e) {
    e.preventDefault()
    doLogin(email, password)
  }

  return (
    <div className="auth-shell">
      <div className="auth-card">
        <div className="auth-brand">
          <span className="brand-mark" style={{ width: 52, height: 52, fontSize: 26 }}>S</span>
          <div>
            <h1>Welcome back</h1>
            <p>Sign in to the Support Desk</p>
          </div>
        </div>

        {error && <div className="error-text">{error}</div>}

        <form onSubmit={handleSubmit}>
          <div className="auth-field">
            <label>Email</label>
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </div>
          <div className="auth-field">
            <label>Password</label>
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
            <p className="hint" style={{ marginTop: 6 }}><Link to="/forgot-password">Forgot password?</Link></p>
          </div>
          <button type="submit" style={{ width: '100%', justifyContent: 'center', padding: 12 }} disabled={signingIn}>
            {signingIn ? 'Signing in…' : 'Sign in'}
          </button>
        </form>

        {demoAccounts.length > 0 && (
          <div className="auth-demo">
            <div className="h">Demo accounts — tap to sign in</div>
            {demoAccounts.map((acc) => (
              <div key={acc.email} className="demo-login" onClick={() => doLogin(acc.email, acc.password)}>
                <span className={`av ${acc.avatar_class}`} style={{ width: 28, height: 28, fontSize: 11 }}>{acc.initials}</span>
                <span style={{ display: 'flex', flexDirection: 'column', minWidth: 0, gap: 1 }}>
                  <span className="r">{acc.name}</span>
                  <span className="hint-text" style={{ fontSize: 11 }}>{acc.role}</span>
                </span>
                <span className="e">{acc.email}</span>
              </div>
            ))}
          </div>
        )}

        <p className="hint" style={{ textAlign: 'center', marginTop: 18 }}>
          No account? <Link to="/register">Register</Link>
        </p>
      </div>
    </div>
  )
}
