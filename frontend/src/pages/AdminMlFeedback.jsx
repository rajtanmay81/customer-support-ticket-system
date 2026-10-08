import { useEffect, useState } from 'react'
import api from '../api/client'

function MetricsTable({ title, metrics }) {
  return (
    <div style={{ flex: '1 1 320px', minWidth: 280 }}>
      <div className="side-h">{title}</div>
      <table>
        <thead>
          <tr>
            <th>Class</th>
            <th>Precision</th>
            <th>Recall</th>
            <th>F1</th>
            <th>Support</th>
          </tr>
        </thead>
        <tbody>
          {metrics.map((m) => (
            <tr key={m.label}>
              <td>{m.label.replace('_', ' ')}</td>
              <td>{Math.round(m.precision * 100)}%</td>
              <td>{Math.round(m.recall * 100)}%</td>
              <td>{Math.round(m.f1_score * 100)}%</td>
              <td>{m.support}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function AdminMlFeedback() {
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(true)
  const [retraining, setRetraining] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')

  async function loadStats() {
    setLoading(true)
    const res = await api.get('/admin/ml/feedback-stats')
    setStats(res.data)
    setLoading(false)
  }

  useEffect(() => { loadStats() }, [])

  async function handleRetrain() {
    setError('')
    setRetraining(true)
    setResult(null)
    try {
      const res = await api.post('/admin/ml/retrain')
      setResult(res.data)
      await loadStats()
    } catch (err) {
      setError(err.response?.data?.detail || 'Retrain failed')
    } finally {
      setRetraining(false)
    }
  }

  return (
    <div>
      <div className="crumbs" style={{ marginBottom: 8 }}>Admin / <b>Model Feedback</b></div>
      <div className="h-title" style={{ marginBottom: 4 }}>ML feedback & retraining</div>
      <div className="h-sub" style={{ marginBottom: 22 }}>
        Every time an agent overrides the ML classifier's suggested category or priority, it's
        logged here as a training example — the active-learning loop. Retrain folds those
        corrections back into the model on demand, without restarting the API.
      </div>

      {error && <div className="error-text" style={{ marginBottom: 16 }}>{error}</div>}

      <div className="card card-pad" style={{ marginBottom: 20 }}>
        <div className="between" style={{ alignItems: 'flex-start' }}>
          <div>
            <div className="side-h">Corrections collected</div>
            {loading ? (
              <p className="hint-text">Loading…</p>
            ) : stats.total === 0 ? (
              <p className="hint-text">No corrections yet — override a ticket's category or priority to start collecting feedback.</p>
            ) : (
              <div className="row" style={{ gap: 20, marginTop: 6 }}>
                <div>
                  <div style={{ fontSize: 22, fontWeight: 700 }}>{stats.total}</div>
                  <div className="hint-text">total corrections</div>
                </div>
                {stats.by_field.map((f) => (
                  <div key={f.field}>
                    <div style={{ fontSize: 22, fontWeight: 700 }}>{f.count}</div>
                    <div className="hint-text">{f.field} corrections</div>
                  </div>
                ))}
              </div>
            )}
          </div>
          <button type="button" onClick={handleRetrain} disabled={retraining}>
            {retraining ? 'Retraining…' : 'Retrain models now'}
          </button>
        </div>
      </div>

      {result && (
        <div className="card card-pad">
          <div className="between" style={{ marginBottom: 14 }}>
            <div className="side-h" style={{ marginBottom: 0 }}>Latest retrain result</div>
            <span className="hint-text">
              {result.dataset_rows} training rows ({result.feedback_rows_included} from real corrections)
            </span>
          </div>
          <div className="row" style={{ gap: 24, flexWrap: 'wrap', alignItems: 'flex-start' }}>
            <MetricsTable title="Category classifier" metrics={result.category_metrics} />
            <MetricsTable title="Priority classifier" metrics={result.priority_metrics} />
          </div>
          <p className="hint" style={{ marginTop: 14 }}>
            New models are already live — no restart needed. Metrics are measured on a held-out
            20% test split of the training data, same as the offline training script.
          </p>
        </div>
      )}
    </div>
  )
}
