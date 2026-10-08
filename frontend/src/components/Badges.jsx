import { slaBadgeInfo } from '../utils/sla'

export function StatusBadge({ status }) {
  return (
    <span className={`badge status-${status}`}>
      <span className="d" />
      {status.replace('_', ' ')}
    </span>
  )
}

export function PriorityBar({ priority }) {
  if (!priority) return <span className="hint-text">unset</span>
  return (
    <span className={`pri pri-${priority}`}>
      <span className="bar"><i></i><i></i><i></i><i></i></span>
      {priority.charAt(0).toUpperCase() + priority.slice(1)}
    </span>
  )
}

export function SLABadge({ ticket }) {
  const info = ticket ? slaBadgeInfo(ticket) : null
  if (!info) return <span className="hint-text">no SLA</span>
  return (
    <span className={`sla ${info.cls}`}>
      <span aria-hidden="true">{info.icon}</span> {info.label}
    </span>
  )
}
