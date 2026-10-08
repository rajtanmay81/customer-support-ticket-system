import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../api/client'
import { PriorityBar } from '../components/Badges'
import FilePicker from '../components/FilePicker'

export default function NewTicket() {
  const [subject, setSubject] = useState('')
  const [description, setDescription] = useState('')
  const [category, setCategory] = useState('')
  const [categories, setCategories] = useState([])
  const [suggestion, setSuggestion] = useState(null)
  const [suggesting, setSuggesting] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [files, setFiles] = useState([])
  const navigate = useNavigate()

  useEffect(() => {
    api.get('/categories').then((res) => setCategories(res.data))
  }, [])

  async function handleSuggest() {
    if (!subject || !description) {
      setError('Fill in subject and description before requesting a suggestion.')
      return
    }
    setError('')
    setSuggesting(true)
    try {
      const res = await api.post('/tickets/classify', { subject, description })
      setSuggestion(res.data)
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not get a suggestion (has the ML model been trained?)')
    } finally {
      setSuggesting(false)
    }
  }

  function applySuggestion() {
    if (!suggestion) return
    setCategory(suggestion.category)
  }

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    setSubmitting(true)
    try {
      const res = await api.post('/tickets', {
        subject,
        description,
        category: category || null,
      })
      if (files.length > 0) {
        const formData = new FormData()
        files.forEach((f) => formData.append('files', f))
        try {
          await api.post(`/tickets/${res.data.id}/attachments`, formData)
        } catch (uploadErr) {
          // Ticket is already created — surface the upload failure but still take them to it.
          setError(uploadErr.response?.data?.detail || 'Ticket created, but attachments failed to upload')
        }
      }
      navigate(`/tickets/${res.data.id}`)
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not create ticket')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div>
      <div className="crumbs" style={{ marginBottom: 8 }}>Tickets / <b>New</b></div>
      <div className="h-title" style={{ marginBottom: 4 }}>Create a support ticket</div>
      <div className="h-sub" style={{ marginBottom: 22 }}>
        Describe the issue — our model will suggest a category and priority automatically.
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 320px', gap: 20, alignItems: 'start' }}>
        <div className="card card-pad">
          {error && <div className="error-text">{error}</div>}
          <form onSubmit={handleSubmit}>
            <label>Subject</label>
            <input type="text" value={subject} onChange={(e) => setSubject(e.target.value)} required />

            <label>Description</label>
            <textarea value={description} onChange={(e) => setDescription(e.target.value)} required />

            <button type="button" className="ai-btn" style={{ marginBottom: 6 }} onClick={handleSuggest} disabled={suggesting}>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="15" height="15"><path d="m12 3 1.9 5.8L20 10l-6.1 1.2L12 17l-1.9-5.8L4 10l6.1-1.2z" /></svg>
              {suggesting ? 'Analyzing…' : 'Suggest category & priority (AI)'}
            </button>

            {suggestion && (
              <div className="classify-box">
                <div className="hint" style={{ fontWeight: 600, color: 'var(--primary-ink)', marginBottom: 6 }}>Model suggestion</div>
                <div className="crow">
                  <span>Category</span>
                  <span className="row">
                    <b>{suggestion.category.replace('_', ' ')}</b>
                    <span className="conf">
                      <span className="track"><span className="fill" style={{ width: `${Math.round(suggestion.category_confidence * 100)}%` }} /></span>
                      {Math.round(suggestion.category_confidence * 100)}%
                    </span>
                  </span>
                </div>
                <div className="crow">
                  <span>Priority</span>
                  <span className="row">
                    <PriorityBar priority={suggestion.priority} />
                    <span className="conf">
                      <span className="track"><span className="fill" style={{ width: `${Math.round(suggestion.priority_confidence * 100)}%` }} /></span>
                      {Math.round(suggestion.priority_confidence * 100)}%
                    </span>
                  </span>
                </div>
                <button type="button" className="btn-soft btn-sm" style={{ marginTop: 10 }} onClick={applySuggestion}>Use this suggestion</button>
              </div>
            )}

            <div className="divider" />

            <div className="row" style={{ gap: 12, alignItems: 'flex-start' }}>
              <div style={{ flex: 1 }}>
                <label>Category (optional override)</label>
                <select value={category} onChange={(e) => setCategory(e.target.value)}>
                  <option value="">Auto-detect</option>
                  {categories.map((c) => <option key={c.id} value={c.name}>{c.name.replace('_', ' ')}</option>)}
                </select>
              </div>
              <div style={{ flex: 1 }}>
                <label>Priority</label>
                <select value={suggestion?.priority || ''} disabled style={{ marginBottom: 6 }}>
                  <option value="">Auto-detect</option>
                  {suggestion && (
                    <option value={suggestion.priority}>
                      {suggestion.priority.charAt(0).toUpperCase() + suggestion.priority.slice(1)}
                    </option>
                  )}
                </select>
                <p className="hint-text">Set automatically by AI — not customer-editable.</p>
              </div>
            </div>

            <div className="divider" />

            <label>Attachments (optional)</label>
            <FilePicker files={files} onChange={setFiles} disabled={submitting} />

            <div className="divider" />

            <div className="row" style={{ justifyContent: 'flex-end', gap: 10 }}>
              <button type="button" className="ghost" onClick={() => navigate('/')}>Cancel</button>
              <button type="submit" disabled={submitting}>{submitting ? 'Submitting…' : 'Submit ticket'}</button>
            </div>
          </form>
        </div>

        <div className="card card-pad" style={{ background: 'var(--surface-2)' }}>
          <div className="side-h">How it works</div>
          <ol style={{ margin: 0, paddingLeft: 18, fontSize: 12.5, color: 'var(--ink-2)', lineHeight: 1.9 }}>
            <li>You describe the problem.</li>
            <li>The ML model reads subject + description and predicts a <b>category</b> and <b>priority</b> with a confidence score.</li>
            <li>An <b>SLA clock</b> starts based on the priority.</li>
            <li>An agent picks it up and can use the <b>AI assistant</b> to summarize, draft a reply, or write resolution notes.</li>
          </ol>
          <div className="notice info" style={{ marginTop: 14 }}>
            You can override the category — your choice wins, but the model's guess is still recorded. Priority is always set by the model.
          </div>
        </div>
      </div>
    </div>
  )
}
