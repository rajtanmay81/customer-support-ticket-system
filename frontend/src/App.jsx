import { Navigate, Route, Routes } from 'react-router-dom'
import { useAuth } from './context/AuthContext'
import AppShell from './components/AppShell'
import Login from './pages/Login'
import Register from './pages/Register'
import ForgotPassword from './pages/ForgotPassword'
import ResetPassword from './pages/ResetPassword'
import TicketList from './pages/TicketList'
import NewTicket from './pages/NewTicket'
import TicketDetail from './pages/TicketDetail'
import AdminUsers from './pages/AdminUsers'
import AdminMonitor from './pages/AdminMonitor'
import AdminMlFeedback from './pages/AdminMlFeedback'
import AdminAnalytics from './pages/AdminAnalytics'

export default function App() {
  const { user, loading, isAdmin } = useAuth()

  if (loading) {
    return <div className="loading-state"><span className="spinner" /> Loading…</div>
  }

  if (!user) {
    return (
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />
        <Route path="/forgot-password" element={<ForgotPassword />} />
        <Route path="/reset-password" element={<ResetPassword />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    )
  }

  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<TicketList />} />
        <Route path="/new" element={<NewTicket />} />
        <Route path="/tickets/:id" element={<TicketDetail />} />
        <Route path="/admin/users" element={isAdmin ? <AdminUsers /> : <Navigate to="/" replace />} />
        <Route path="/admin/monitor" element={isAdmin ? <AdminMonitor /> : <Navigate to="/" replace />} />
        <Route path="/admin/ml-feedback" element={isAdmin ? <AdminMlFeedback /> : <Navigate to="/" replace />} />
        <Route path="/admin/analytics" element={isAdmin ? <AdminAnalytics /> : <Navigate to="/" replace />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AppShell>
  )
}
