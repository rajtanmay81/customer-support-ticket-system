import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import api from '../api/client'
import { useAuth } from '../context/AuthContext'
import { StatusBadge, PriorityBar, SLABadge } from '../components/Badges'
import Avatar from '../components/Avatar'
import FilePicker from '../components/FilePicker'
import AttachmentList from '../components/AttachmentList'
import LiveDot from '../components/LiveDot'
import useWebSocket from '../hooks/useWebSocket'
import { slaInfo, slaHeadline, formatDuration, formatDateTime } from '../utils/sla'

const STATUSES = ['open', 'in_progress', 'resolved', 'closed']
const RING_RADIUS = 42
const RING_CIRCUMFERENCE = 2 * Math.PI * RING_RADIUS

const AI_LABELS = {
  summarize: 'Summary',
  'draft-reply': 'Draft reply',
  'resolution-notes': 'Resolution notes',
}

function SLARing({ ticket }) {
  const info = slaInfo(ticket)
  if (!info) {
    return (
      <div className="card side-card sla-panel card-pad">
        <div className="side-h">SLA status</div>
        <p className="hint" style={{ color: '#8592b3' }}>No SLA clock yet — set a priority to start it.</p>
      </div>
    )
  }

  const done = info.stage === 'done'
  const breach = info.state === 'breach'
  const offset = done ? 0 : RING_CIRCUMFERENCE * (info.percent / 100)
  const stroke = done ? (breach ? 'var(--danger)' : 'var(--ok)') : breach ? 'var(--danger)' : 'url(#slaGradient)'
  const headline = slaHeadline(info)

  let big, cap
  if (done) {
    big = breach ? 'Missed' : '✓'
    cap = breach ? 'SLA missed' : 'SLA met'
  } else if (breach) {
    big = formatDuration(Math.abs(info.remainingMs))
    cap = 'overdue'
  } else {
    big = formatDuration(info.remainingMs)
    cap = 'remaining'
  }

  return (
    <div className="card side-card sla-panel card-pad">
      <div className="side-h">SLA status</div>
      <div className={`sla-headline ${headline.cls}`}>
        <span aria-hidden="true">{headline.icon}</span> {headline.text}
      </div>
      <div className="ring-wrap">
        <div className="ring">
          <svg width="96" height="96" viewBox="0 0 96 96">
            <circle cx="48" cy="48" r={RING_RADIUS} fill="none" stroke="#26314e" strokeWidth="9" />
            <circle
              cx="48" cy="48" r={RING_RADIUS} fill="none" stroke={stroke} strokeWidth="9" strokeLinecap="round"
              strokeDasharray={RING_CIRCUMFERENCE} strokeDashoffset={offset}
              style={{ transition: 'stroke-dashoffset .4s ease' }}
            />
            <defs>
              <linearGradient id="slaGradient" x1="0" y1="0" x2="1" y2="1">
                <stop offset="0" stopColor="#ffd166" />
                <stop offset="1" stopColor="#ef8a3c" />
              </linearGradient>
            </defs>
          </svg>
          <div className="mid"><div className="big">{big}</div><div className="cap">{cap}</div></div>
        </div>
        <div className="sla-lines">
          <div className="sla-line">
            <span className="k">First response</span>
            <span className={`v ${info.responseDone ? 'ok' : info.responseBreached ? 'breach' : ''}`}>
              {info.responseDone ? '✓ met' : info.responseBreached ? 'Breached' : `Due ${formatDateTime(info.responseDue)}`}
            </span>
          </div>
          <div className="sla-line">
            <span className="k">Resolution</span>
            <span className={`v ${info.resolutionDone ? 'ok' : info.resolutionBreached ? 'breach' : ''}`}>
              {info.resolutionDone ? '✓ met' : info.resolutionBreached ? 'Breached' : `Due ${formatDateTime(info.resolutionDue)}`}
            </span>
          </div>
          <div className="sla-line">
            <span className="k">Policy</span>
            <span className="v">{ticket.priority ? ticket.priority.charAt(0).toUpperCase() + ticket.priority.slice(1) : '—'} · {info.policyHours}h</span>
          </div>
        </div>
      </div>
    </div>
  )
}

export default function TicketDetail() {
  const { id } = useParams()
  const { user, isStaff, isAdmin } = useAuth()

  const [ticket, setTicket] = useState(null)
  const [loadError, setLoadError] = useState(null)
  const [categories, setCategories] = useState([])
  const [priorities, setPriorities] = useState([])
  const [agents, setAgents] = useState([])
  const [similar, setSimilar] = useState([])
  const [similarLoading, setSimilarLoading] = useState(false)

  const [commentBody, setCommentBody] = useState('')
  const [isInternal, setIsInternal] = useState(false)
  const [posting, setPosting] = useState(false)
  const [error, setError] = useState('')
  const [replyFiles, setReplyFiles] = useState([])

  const [aiLoading, setAiLoading] = useState(null)
  const [aiOutput, setAiOutput] = useState(null)
  const [copied, setCopied] = useState(false)

  const [showClosedModal, setShowClosedModal] = useState(false)

  const [ratingStars, setRatingStars] = useState(0)
  const [ratingComment, setRatingComment] = useState('')
  const [submittingRating, setSubmittingRating] = useState(false)
  const [editingRating, setEditingRating] = useState(false)

  const [canned, setCanned] = useState([])
  const [suggestedCanned, setSuggestedCanned] = useState([])
  const [showCannedModal, setShowCannedModal] = useState(false)
  const [cannedForm, setCannedForm] = useState({ title: '', body: '', category: '' })
  const [cannedEditingId, setCannedEditingId] = useState(null)
  const [cannedError, setCannedError] = useState('')

  const [live, setLive] = useState(false)
  const [reassigning, setReassigning] = useState(false)

  const initialLoadRef = useRef(true)

  function handleWsMessage(event) {
    if (event.type === 'comment.created') {
      setTicket((prev) => {
        if (!prev || prev.comments.some((c) => c.id === event.data.id)) return prev
        return { ...prev, comments: [...prev.comments, event.data] }
      })
    } else if (event.type === 'ticket.updated' || event.type === 'ticket.created') {
      setTicket((prev) => (prev ? { ...prev, ...event.data } : prev))
    }
  }

  useWebSocket(`/ws/tickets/${id}`, handleWsMessage, !!id, setLive)

  async function loadTicket() {
    try {
      const res = await api.get(`/tickets/${id}`)
      setTicket(res.data)
      if (!isStaff && res.data.status === 'closed' && initialLoadRef.current) {
        setShowClosedModal(true)
      }
      initialLoadRef.current = false
      setRatingStars(res.data.rating?.stars || 0)
      setRatingComment(res.data.rating?.comment || '')
    } catch (err) {
      setLoadError(err.response?.status === 403 ? "You don't have access to this ticket." : 'Ticket not found.')
    }
  }

  async function loadCanned() {
    const res = await api.get('/canned-responses')
    setCanned(res.data)
  }

  async function loadSuggestedCanned() {
    try {
      const res = await api.get('/canned-responses/suggest', { params: { ticket_id: id, top_k: 3 } })
      setSuggestedCanned(res.data)
    } catch {
      setSuggestedCanned([])
    }
  }

  useEffect(() => {
    initialLoadRef.current = true
    loadTicket()
    api.get('/categories').then((res) => setCategories(res.data))
    api.get('/priorities').then((res) => setPriorities(res.data))
    if (isAdmin) {
      api.get('/agents').then((res) => setAgents(res.data))
    }
    if (isStaff) {
      setSimilarLoading(true)
      api.get(`/tickets/${id}/similar`)
        .then((res) => setSimilar(res.data))
        .catch(() => setSimilar([]))
        .finally(() => setSimilarLoading(false))
      loadCanned()
      loadSuggestedCanned()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id])

  async function handleUpdate(field, value) {
    setError('')
    try {
      await api.patch(`/tickets/${id}`, { [field]: value })
      loadTicket()
    } catch (err) {
      setError(err.response?.data?.detail || 'Update failed')
    }
  }

  async function handleAiReassign() {
    setError('')
    setReassigning(true)
    try {
      const res = await api.post(`/tickets/${id}/ai/reassign`, {})
      setTicket((prev) => (prev ? { ...prev, ...res.data } : prev))
    } catch (err) {
      setError(err.response?.data?.detail || 'AI reassignment failed')
    } finally {
      setReassigning(false)
    }
  }

  async function handleAddComment(e) {
    e.preventDefault()
    setPosting(true)
    setError('')
    try {
      const res = await api.post(`/tickets/${id}/comments`, { body: commentBody, is_internal_note: isInternal })
      if (replyFiles.length > 0) {
        const formData = new FormData()
        replyFiles.forEach((f) => formData.append('files', f))
        formData.append('comment_id', res.data.id)
        try {
          await api.post(`/tickets/${id}/attachments`, formData)
        } catch (uploadErr) {
          setError(uploadErr.response?.data?.detail || 'Reply posted, but attachments failed to upload')
        }
      }
      setCommentBody('')
      setIsInternal(false)
      setReplyFiles([])
      loadTicket()
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not post comment')
    } finally {
      setPosting(false)
    }
  }

  async function handleDeleteAttachment(attachment) {
    try {
      await api.delete(`/attachments/${attachment.id}`)
      loadTicket()
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not delete attachment')
    }
  }

  function canDeleteAttachment(attachment) {
    return isAdmin || attachment.uploaded_by_id === user.id
  }

  async function submitRating() {
    setSubmittingRating(true)
    setError('')
    try {
      await api.put(`/tickets/${id}/rating`, { stars: ratingStars, comment: ratingComment || null })
      setEditingRating(false)
      loadTicket()
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not submit rating')
    } finally {
      setSubmittingRating(false)
    }
  }

  function insertCannedBody(body) {
    setCommentBody((prev) => (prev ? `${prev}\n\n${body}` : body))
  }

  function insertCanned(responseId) {
    const cr = canned.find((c) => c.id === Number(responseId))
    if (!cr) return
    insertCannedBody(cr.body)
  }

  function openCannedModal() {
    setCannedEditingId(null)
    setCannedForm({ title: '', body: '', category: '' })
    setCannedError('')
    setShowCannedModal(true)
  }

  function editCanned(cr) {
    setCannedEditingId(cr.id)
    setCannedForm({ title: cr.title, body: cr.body, category: cr.category || '' })
    setCannedError('')
  }

  async function handleSaveCanned(e) {
    e.preventDefault()
    setCannedError('')
    const payload = { title: cannedForm.title, body: cannedForm.body, category: cannedForm.category || null }
    try {
      if (cannedEditingId) {
        await api.patch(`/canned-responses/${cannedEditingId}`, payload)
      } else {
        await api.post('/canned-responses', payload)
      }
      setCannedEditingId(null)
      setCannedForm({ title: '', body: '', category: '' })
      loadCanned()
    } catch (err) {
      setCannedError(err.response?.data?.detail || 'Could not save canned response')
    }
  }

  async function handleDeleteCanned(cr) {
    setCannedError('')
    try {
      await api.delete(`/canned-responses/${cr.id}`)
      loadCanned()
    } catch (err) {
      setCannedError(err.response?.data?.detail || 'Could not delete canned response')
    }
  }

  async function runAi(kind) {
    setAiLoading(kind)
    setAiOutput(null)
    setCopied(false)
    setError('')
    try {
      const res = await api.post(`/tickets/${id}/ai/${kind}`, {})
      setAiOutput({ kind, text: res.data.text })
    } catch (err) {
      setError(err.response?.data?.detail || 'AI request failed')
    } finally {
      setAiLoading(null)
    }
  }

  function useDraftAsComment() {
    if (aiOutput?.kind === 'draft-reply') {
      setCommentBody(aiOutput.text)
    }
  }

  async function copyOutput() {
    if (!aiOutput) return
    try {
      await navigator.clipboard.writeText(aiOutput.text)
      setCopied(true)
      setTimeout(() => setCopied(false), 1800)
    } catch {
      // clipboard API unavailable — silently ignore, the text is still visible to select/copy manually
    }
  }

  if (loadError) {
    return (
      <div className="empty">
        <div className="ei">
          <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6"><path d="M12 9v4M12 17h.01" /><circle cx="12" cy="12" r="9" /></svg>
        </div>
        <h3>{loadError}</h3>
        <Link to="/" className="ghost btn-sm" style={{ marginTop: 10, display: 'inline-flex' }}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="15" height="15"><path d="m15 18-6-6 6-6" /></svg>
          Back to tickets
        </Link>
      </div>
    )
  }

  if (!ticket) return <div className="loading-state"><span className="spinner" /> Loading ticket…</div>

  // Reaching this point at all means the backend granted at least read access (a
  // stranger agent gets a 403 on GET and never gets here — see assert_can_view).
  // So for staff, "not currently assigned" here only ever means "used to be assigned,
  // reassigned away since" — i.e. read-only (see assert_can_write on the backend).
  const isReadOnlyAgent = isStaff && !isAdmin && ticket.assigned_agent_id !== user.id

  // The GenAI assistant (genai_service.py) reads screenshots attached to the ticket or
  // to any non-internal reply, up to 4 — this mirrors that so the panel can tell the
  // agent it's actually looking at them, not just the text.
  const isImage = (a) => a.content_type?.startsWith('image/')
  const imageAttachmentCount =
    (ticket.attachments || []).filter(isImage).length +
    (ticket.comments || [])
      .filter((c) => !c.is_internal_note)
      .reduce((sum, c) => sum + (c.attachments || []).filter(isImage).length, 0)

  return (
    <div>
      {showClosedModal && (
        <div className="modal-overlay" onClick={() => setShowClosedModal(false)}>
          <div className="modal-card" onClick={(e) => e.stopPropagation()}>
            <div className="mi">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6"><rect x="4" y="10" width="16" height="10" rx="2" /><path d="M8 10V7a4 4 0 0 1 8 0v3" /></svg>
            </div>
            <h3>This ticket is closed</h3>
            <p>This ticket has been closed and can no longer receive replies. If you still need help, please raise a new ticket.</p>
            <div className="row" style={{ justifyContent: 'center', gap: 10 }}>
              <button className="secondary" onClick={() => setShowClosedModal(false)}>Dismiss</button>
              <Link to="/new" className="btn">Raise a new ticket</Link>
            </div>
          </div>
        </div>
      )}

      {showCannedModal && (
        <div className="modal-overlay" onClick={() => setShowCannedModal(false)}>
          <div className="modal-card wide" onClick={(e) => e.stopPropagation()}>
            <h3>Canned responses</h3>
            {cannedError && <div className="error-text">{cannedError}</div>}

            <form onSubmit={handleSaveCanned} style={{ marginBottom: 18 }}>
              <label>Title</label>
              <input
                type="text"
                value={cannedForm.title}
                onChange={(e) => setCannedForm({ ...cannedForm, title: e.target.value })}
                required
              />
              <label>Body</label>
              <textarea
                value={cannedForm.body}
                onChange={(e) => setCannedForm({ ...cannedForm, body: e.target.value })}
                required
              />
              <label>Category (optional)</label>
              <input
                type="text"
                value={cannedForm.category}
                onChange={(e) => setCannedForm({ ...cannedForm, category: e.target.value })}
              />
              <div className="row" style={{ justifyContent: 'flex-end', gap: 8, marginTop: 10 }}>
                {cannedEditingId && (
                  <button
                    type="button"
                    className="ghost"
                    onClick={() => { setCannedEditingId(null); setCannedForm({ title: '', body: '', category: '' }) }}
                  >
                    Cancel edit
                  </button>
                )}
                <button type="submit">{cannedEditingId ? 'Save changes' : '+ New canned response'}</button>
              </div>
            </form>

            <div className="divider" />

            {canned.length === 0 && <p className="hint-text">No canned responses yet.</p>}
            {canned.map((cr) => (
              <div key={cr.id} className="kv" style={{ alignItems: 'flex-start' }}>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontWeight: 600 }}>{cr.title}{cr.category && <span className="hint-text"> · {cr.category}</span>}</div>
                  <div className="hint-text">by {cr.created_by_name}</div>
                </div>
                <div className="row" style={{ gap: 6 }}>
                  <button type="button" className="ghost btn-sm" onClick={() => editCanned(cr)}>Edit</button>
                  <button type="button" className="ghost btn-sm" onClick={() => handleDeleteCanned(cr)}>Delete</button>
                </div>
              </div>
            ))}

            <div className="row" style={{ justifyContent: 'center', marginTop: 16 }}>
              <button className="secondary" onClick={() => setShowCannedModal(false)}>Close</button>
            </div>
          </div>
        </div>
      )}

      <div className="row" style={{ marginBottom: 14, gap: 10 }}>
        <Link to="/" className="ghost btn-sm">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="15" height="15"><path d="m15 18-6-6 6-6" /></svg>
          Back to tickets
        </Link>
        <span className="tk-id">#{ticket.id}</span>
      </div>

      <div className="between" style={{ marginBottom: 18 }}>
        <div style={{ minWidth: 0 }}>
          <div className="h-title" style={{ fontSize: 20 }}>{ticket.subject}</div>
          <div className="row" style={{ gap: 10, marginTop: 8, flexWrap: 'wrap' }}>
            <StatusBadge status={ticket.status} />
            <PriorityBar priority={ticket.priority} />
            {ticket.category && <span style={{ fontSize: 12.5, color: 'var(--ink-2)' }}>{ticket.category.replace('_', ' ')}</span>}
            <SLABadge ticket={ticket} />
          </div>
        </div>
      </div>

      {isReadOnlyAgent && (
        <div className="notice info" style={{ marginBottom: 16 }}>
          <svg width="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ flex: 'none', marginTop: 1 }}><path d="M12 9v4M12 17h.01" /><circle cx="12" cy="12" r="9" /></svg>
          This ticket was reassigned to {ticket.assigned_agent_name || 'another agent'} — you have read-only access and can no longer reply or make changes.
        </div>
      )}

      {error && <div className="error-text">{error}</div>}

      <div className="detail">
        {/* LEFT: conversation + AI */}
        <div>
          <div className="card card-pad">
            <div className="between" style={{ marginBottom: 0 }}>
              <div className="side-h" style={{ marginBottom: 12 }}>Conversation</div>
              <LiveDot connected={live} />
            </div>
            {ticket.suggested_category && (
              <p className="hint-text">
                ML suggested: {ticket.suggested_category.replace('_', ' ')} ({Math.round(ticket.category_confidence * 100)}%)
                {' '}/ {ticket.suggested_priority} ({Math.round(ticket.priority_confidence * 100)}%)
              </p>
            )}
            <p style={{ fontSize: 13.5, lineHeight: 1.6, marginBottom: ticket.attachments?.length ? 10 : 16 }}>{ticket.description}</p>
            {ticket.attachments?.length > 0 && (
              <div style={{ marginBottom: 16 }}>
                <AttachmentList
                  attachments={ticket.attachments}
                  onDelete={handleDeleteAttachment}
                  canDelete={canDeleteAttachment}
                />
              </div>
            )}

            <div className="thread">
              {ticket.comments.length === 0 && <p className="hint-text">No replies yet — be the first to respond.</p>}
              {ticket.comments.map((c) => (
                <div key={c.id} className={`msg${c.is_internal_note ? ' internal' : ''}`}>
                  {!c.is_internal_note && <Avatar name={c.author_name} size={38} />}
                  <div className="body">
                    <div className="meta">
                      {c.is_internal_note ? (
                        <span className="note-flag">📌 Internal note</span>
                      ) : (
                        <span className="who">{c.author_name}</span>
                      )}
                      <span className="role-tag">
                        {c.author_id === ticket.customer_id ? 'customer' : c.is_ai_generated ? 'AI assistant' : 'agent'}
                      </span>
                      {c.sentiment && (
                        <span className={`role-tag sentiment-${c.sentiment}`}>
                          {{ angry: '😠 angry', frustrated: '😕 frustrated', satisfied: '🙂 satisfied', neutral: '😐 neutral' }[c.sentiment] || c.sentiment}
                        </span>
                      )}
                      <span className="time">{new Date(c.created_at).toLocaleString()}</span>
                    </div>
                    <div className="text">{c.body}</div>
                    {c.attachments?.length > 0 && (
                      <div style={{ marginTop: 8 }}>
                        <AttachmentList
                          attachments={c.attachments}
                          onDelete={handleDeleteAttachment}
                          canDelete={canDeleteAttachment}
                        />
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>

            {isStaff && !isReadOnlyAgent && suggestedCanned.length > 0 && (
              <div style={{ marginTop: 14 }}>
                <div className="side-h" style={{ marginBottom: 8 }}>Suggested for this ticket</div>
                <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
                  {suggestedCanned.map((cr) => (
                    <button
                      key={cr.id}
                      type="button"
                      className="chip"
                      title={cr.body}
                      onClick={() => insertCannedBody(cr.body)}
                    >
                      {cr.title}
                      {cr.similarity > 0 && <span className="n">{Math.round(cr.similarity * 100)}%</span>}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {isReadOnlyAgent ? (
              <div className="notice info" style={{ marginTop: 14 }}>
                <svg width="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ flex: 'none', marginTop: 1 }}><path d="M12 9v4M12 17h.01" /><circle cx="12" cy="12" r="9" /></svg>
                You no longer have write access to this conversation — read-only.
              </div>
            ) : !isStaff && ticket.status === 'closed' ? (
              <div className="notice info" style={{ marginTop: 14 }}>
                <svg width="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ flex: 'none', marginTop: 1 }}><path d="M12 9v4M12 17h.01" /><circle cx="12" cy="12" r="9" /></svg>
                This ticket is closed and can no longer receive replies. Need more help? <Link to="/new">Raise a new ticket</Link>.
              </div>
            ) : (
              <form onSubmit={handleAddComment} className="composer" style={{ marginTop: 14 }}>
                <textarea
                  placeholder="Write a reply to the customer…"
                  value={commentBody}
                  onChange={(e) => setCommentBody(e.target.value)}
                  required
                />
                <div style={{ padding: '0 12px 10px' }}>
                  <FilePicker files={replyFiles} onChange={setReplyFiles} disabled={posting} />
                </div>
                <div className="foot">
                  {isStaff && (
                    <label className="toggle">
                      <input
                        type="checkbox"
                        className="switch-input"
                        checked={isInternal}
                        onChange={(e) => setIsInternal(e.target.checked)}
                      />
                      <span className="switch"><i></i></span>
                      Internal note
                    </label>
                  )}
                  {isStaff && (
                    <div className="select">
                      <select value="" onChange={(e) => insertCanned(e.target.value)}>
                        <option value="" disabled>Canned response…</option>
                        {canned.map((c) => <option key={c.id} value={c.id}>{c.title}</option>)}
                      </select>
                    </div>
                  )}
                  {isStaff && (
                    <button type="button" className="ghost btn-sm" onClick={openCannedModal}>Manage</button>
                  )}
                  <button type="submit" className="btn-sm" style={{ marginLeft: 'auto' }} disabled={posting}>
                    {posting ? 'Posting…' : 'Send reply'}
                  </button>
                </div>
              </form>
            )}
          </div>

          {isStaff && !isReadOnlyAgent && (
            <div className="ai-panel">
              <div className="ai-head">
                <div className="spark">
                  <svg width="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="m12 3 1.9 5.8L20 10l-6.1 1.2L12 17l-1.9-5.8L4 10l6.1-1.2z" /></svg>
                </div>
                <div>
                  <div className="t">AI Assistant</div>
                  <div className="s">
                    Powered by Gemini · drafts only, never auto-sent
                    {imageAttachmentCount > 0 && ` · sees ${imageAttachmentCount} screenshot${imageAttachmentCount === 1 ? '' : 's'}`}
                  </div>
                </div>
              </div>
              <div className="ai-actions">
                <button className="ai-btn" disabled={!!aiLoading} onClick={() => runAi('summarize')}>
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M4 6h16M4 12h16M4 18h10" /></svg>
                  {aiLoading === 'summarize' ? 'Summarizing…' : 'Summarize thread'}
                </button>
                <button className="ai-btn" disabled={!!aiLoading} onClick={() => runAi('draft-reply')}>
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M3 12h18M3 12l6-6M3 12l6 6" /></svg>
                  {aiLoading === 'draft-reply' ? 'Drafting…' : 'Draft reply'}
                </button>
                <button className="ai-btn" disabled={!!aiLoading} onClick={() => runAi('resolution-notes')}>
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M9 11H5a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-6a2 2 0 0 0-2-2h-4M9 7l3-3 3 3M12 4v11" /></svg>
                  {aiLoading === 'resolution-notes' ? 'Generating…' : 'Resolution notes'}
                </button>
              </div>

              {aiOutput && (
                <>
                  <div className="ai-out">
                    <div className="obar">
                      <span className="tag">{AI_LABELS[aiOutput.kind]}</span>
                      Generated just now
                      <span className="cp" onClick={copyOutput}>
                        <svg width="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="9" y="9" width="11" height="11" rx="2" /><path d="M5 15V5a2 2 0 0 1 2-2h10" /></svg>
                        {copied ? 'Copied!' : 'Copy'}
                      </span>
                    </div>
                    <div className="txt">{aiOutput.text}</div>
                  </div>
                  {aiOutput.kind === 'draft-reply' && (
                    <>
                      <div style={{ padding: '0 18px 6px' }}>
                        <button className="ghost" onClick={useDraftAsComment}>Use as reply draft ↑</button>
                      </div>
                      <div className="ai-draft-note">
                        <svg width="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 9v4M12 17h.01" /><circle cx="12" cy="12" r="9" /></svg>
                        This is a draft. Review and edit before sending — nothing is sent automatically.
                      </div>
                    </>
                  )}
                </>
              )}
            </div>
          )}
        </div>

        {/* RIGHT: SLA + details + manage */}
        <div>
          <SLARing ticket={ticket} />

          <div className="card side-card card-pad">
            <div className="side-h">Details</div>
            <div className="kv">
              <span className="k">Customer</span>
              <span className="v cell-user"><Avatar name={ticket.customer_name} size={22} />{ticket.customer_name}</span>
            </div>
            <div className="kv">
              <span className="k">Assigned</span>
              {ticket.assigned_agent_name
                ? <span className="v cell-user"><Avatar name={ticket.assigned_agent_name} size={22} />{ticket.assigned_agent_name}</span>
                : ticket.handling_mode === 'ai'
                  ? <span className="v hint-text">🤖 AI Assistant is handling this</span>
                  : <span className="v hint-text">Unassigned</span>}
            </div>
            {ticket.assignment_note && (
              <div className="assignment-note">
                <span className={`assignment-tag ${ticket.assignment_source}`}>
                  {ticket.assignment_source === 'ai_escalation' ? '🚨 Escalated by AI'
                    : ticket.assignment_source === 'ai' ? '✨ AI assigned'
                    : ticket.assignment_source === 'admin' ? '👤 Manual'
                    : 'Unassigned'}
                </span>
                {ticket.assignment_note}
              </div>
            )}
            <div className="kv"><span className="k">Created</span><span className="v">{formatDateTime(ticket.created_at)}</span></div>
            <div className="kv"><span className="k">Updated</span><span className="v">{formatDateTime(ticket.updated_at)}</span></div>
            {ticket.suggested_category && (
              <div className="kv">
                <span className="k">ML category</span>
                <span className="v conf">
                  {ticket.suggested_category.replace('_', ' ')}
                  <span className="track"><span className="fill" style={{ width: `${Math.round(ticket.category_confidence * 100)}%` }} /></span>
                  {Math.round(ticket.category_confidence * 100)}%
                </span>
              </div>
            )}
            {ticket.suggested_priority && (
              <div className="kv">
                <span className="k">ML priority</span>
                <span className="v conf">
                  {ticket.suggested_priority}
                  <span className="track"><span className="fill" style={{ width: `${Math.round(ticket.priority_confidence * 100)}%` }} /></span>
                  {Math.round(ticket.priority_confidence * 100)}%
                </span>
              </div>
            )}
          </div>

          {(ticket.status === 'resolved' || ticket.status === 'closed') && (
            <div className="card side-card card-pad">
              <div className="side-h">Customer satisfaction</div>
              {isStaff ? (
                ticket.rating ? (
                  <>
                    <div className="stars">
                      {[1, 2, 3, 4, 5].map((n) => (
                        <span key={n} className={`star readonly${n <= ticket.rating.stars ? ' filled' : ''}`}>
                          <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="m12 2 3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01z" /></svg>
                        </span>
                      ))}
                    </div>
                    {ticket.rating.comment && <p className="hint-text" style={{ marginTop: 8 }}>{ticket.rating.comment}</p>}
                  </>
                ) : (
                  <p className="hint-text">Not yet rated.</p>
                )
              ) : ticket.rating && !editingRating ? (
                <>
                  <div className="stars">
                    {[1, 2, 3, 4, 5].map((n) => (
                      <span key={n} className={`star readonly${n <= ticket.rating.stars ? ' filled' : ''}`}>
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="m12 2 3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01z" /></svg>
                      </span>
                    ))}
                  </div>
                  {ticket.rating.comment && <p className="hint-text" style={{ marginTop: 8 }}>{ticket.rating.comment}</p>}
                  <button
                    type="button"
                    className="ghost btn-sm"
                    style={{ marginTop: 10 }}
                    onClick={() => setEditingRating(true)}
                  >
                    Edit feedback
                  </button>
                </>
              ) : (
                <>
                  <div className="stars">
                    {[1, 2, 3, 4, 5].map((n) => (
                      <button
                        key={n}
                        type="button"
                        className={`star${n <= ratingStars ? ' filled' : ''}`}
                        onClick={() => setRatingStars(n)}
                      >
                        <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor"><path d="m12 2 3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01z" /></svg>
                      </button>
                    ))}
                  </div>
                  <textarea
                    placeholder="Optional comment…"
                    value={ratingComment}
                    onChange={(e) => setRatingComment(e.target.value)}
                    style={{ marginTop: 10, minHeight: 60 }}
                  />
                  <div className="row" style={{ gap: 8, marginTop: 8 }}>
                    <button
                      type="button"
                      className="btn-sm"
                      disabled={ratingStars === 0 || submittingRating}
                      onClick={submitRating}
                    >
                      {submittingRating ? 'Saving…' : ticket.rating ? 'Update feedback' : 'Submit feedback'}
                    </button>
                    {ticket.rating && (
                      <button
                        type="button"
                        className="ghost btn-sm"
                        onClick={() => {
                          setEditingRating(false)
                          setRatingStars(ticket.rating.stars)
                          setRatingComment(ticket.rating.comment || '')
                        }}
                      >
                        Cancel
                      </button>
                    )}
                  </div>
                </>
              )}
            </div>
          )}

          {isStaff && (
            <div className="card side-card card-pad">
              <div className="side-h">Similar past tickets</div>
              {similarLoading && <p className="hint-text">Searching…</p>}
              {!similarLoading && similar.length === 0 && (
                <p className="hint-text">No similar resolved tickets found yet.</p>
              )}
              {similar.map((s) => {
                const row = (
                  <>
                    <span
                      className="k"
                      style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                    >
                      #{s.id} {s.subject}
                    </span>
                    <span className="v">{Math.round(s.similarity * 100)}%</span>
                  </>
                )
                return s.viewable ? (
                  <Link key={s.id} to={`/tickets/${s.id}`} className="kv" style={{ textDecoration: 'none' }}>
                    {row}
                  </Link>
                ) : (
                  <div key={s.id} className="kv" style={{ opacity: 0.7, cursor: 'default' }} title="Assigned to another agent">
                    {row}
                  </div>
                )
              })}
            </div>
          )}

          {isStaff && !isReadOnlyAgent && (
            <div className="card side-card card-pad">
              <div className="side-h">Manage ticket</div>
              <label>Status</label>
              <select value={ticket.status} onChange={(e) => handleUpdate('status', e.target.value)}>
                {STATUSES.map((s) => <option key={s} value={s}>{s.replace('_', ' ')}</option>)}
              </select>

              <label>Priority</label>
              <select value={ticket.priority || ''} onChange={(e) => handleUpdate('priority', e.target.value)}>
                <option value="" disabled>Select priority</option>
                {priorities.map((p) => <option key={p.id} value={p.name}>{p.name.charAt(0).toUpperCase() + p.name.slice(1)}</option>)}
              </select>

              <label>Category</label>
              <select value={ticket.category || ''} onChange={(e) => handleUpdate('category', e.target.value)}>
                <option value="" disabled>Select category</option>
                {categories.map((c) => <option key={c.id} value={c.name}>{c.name.replace('_', ' ')}</option>)}
              </select>

              <label>Assigned agent</label>
              {isAdmin ? (
                <>
                  <div className="row" style={{ gap: 8, alignItems: 'flex-start' }}>
                    <select
                      style={{ flex: 1 }}
                      value={ticket.assigned_agent_id || ''}
                      onChange={(e) => handleUpdate('assigned_agent_id', Number(e.target.value))}
                    >
                      <option value="" disabled>Unassigned</option>
                      {agents.map((a) => (
                        <option key={a.id} value={a.id}>
                          {a.name} · {a.availability} · {a.active_ticket_count} active
                        </option>
                      ))}
                    </select>
                    <button
                      type="button"
                      className="ghost btn-sm"
                      style={{ marginBottom: 14, flex: 'none' }}
                      disabled={reassigning}
                      onClick={handleAiReassign}
                      title="Let the AI pick the best available agent"
                    >
                      {reassigning ? 'Assigning…' : '✨ Auto-assign'}
                    </button>
                  </div>
                </>
              ) : (
                <p className="hint-text">{ticket.assigned_agent_name || 'Unassigned'}</p>
              )}
              <p className="hint" style={{ margin: 0 }}>Changes save instantly — each field updates on change.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
