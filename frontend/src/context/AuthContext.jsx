import { createContext, useContext, useEffect, useState } from 'react'
import api from '../api/client'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const token = localStorage.getItem('token')
    if (!token) {
      setLoading(false)
      return
    }
    api
      .get('/auth/me')
      .then((res) => setUser(res.data))
      .catch(() => localStorage.removeItem('token'))
      .finally(() => setLoading(false))
  }, [])

  async function login(email, password) {
    const res = await api.post('/auth/login', { email, password })
    localStorage.setItem('token', res.data.access_token)
    setUser(res.data.user)
  }

  async function register(name, email, password) {
    const res = await api.post('/auth/register', { name, email, password })
    localStorage.setItem('token', res.data.access_token)
    setUser(res.data.user)
  }

  function logout() {
    localStorage.removeItem('token')
    setUser(null)
  }

  async function setAvailability(availability) {
    setUser((prev) => (prev ? { ...prev, availability } : prev)) // optimistic
    try {
      const res = await api.patch('/auth/me/availability', { availability })
      setUser(res.data)
    } catch {
      // best-effort — a later /auth/me load will resync if this failed
    }
  }

  const isStaff = !!user && (user.role === 'agent' || user.role === 'admin')
  const isAdmin = !!user && user.role === 'admin'

  return (
    <AuthContext.Provider value={{ user, loading, login, register, logout, isStaff, isAdmin, setAvailability }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}
