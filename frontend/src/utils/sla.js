// SLA breach flags (`response_breached` / `resolution_breached`) already come
// from the API pre-computed live on every read (see backend sla_service.refresh_breach_flags) -
// this file only derives *presentation* details (time remaining, ring percent, labels)
// from those flags plus the due-at timestamps, it never re-decides breach state itself.

export function formatDuration(ms) {
  const abs = Math.abs(ms)
  const totalMinutes = Math.round(abs / 60000)
  const days = Math.floor(totalMinutes / (60 * 24))
  const hours = Math.floor((totalMinutes % (60 * 24)) / 60)
  const minutes = totalMinutes % 60
  if (days > 0) return `${days}d ${hours}h`
  if (hours > 0) return `${hours}h ${minutes}m`
  return `${minutes}m`
}

export function formatDateTime(iso) {
  return new Date(iso).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

const WARN_THRESHOLD_MS = 2 * 60 * 60 * 1000

export function slaInfo(ticket) {
  const sla = ticket.sla
  if (!sla) return null

  const created = new Date(ticket.created_at).getTime()
  const responseDue = new Date(sla.response_due_at).getTime()
  const resolutionDue = new Date(sla.resolution_due_at).getTime()
  const responseDone = !!sla.first_response_at
  const resolutionDone = !!sla.resolved_at

  const stage = !responseDone ? 'response' : !resolutionDone ? 'resolution' : 'done'
  const activeDue = stage === 'response' ? responseDue : stage === 'resolution' ? resolutionDue : null
  const activeBreached =
    stage === 'response'
      ? sla.response_breached
      : stage === 'resolution'
      ? sla.resolution_breached
      : sla.response_breached || sla.resolution_breached

  let percent = 100
  let remainingMs = null
  let state

  if (stage === 'done') {
    state = activeBreached ? 'breach' : 'done'
  } else {
    const now = Date.now()
    const totalMs = Math.max(activeDue - created, 1)
    percent = Math.min(Math.max(((now - created) / totalMs) * 100, 0), 100)
    remainingMs = activeDue - now
    state = activeBreached ? 'breach' : remainingMs < WARN_THRESHOLD_MS ? 'warn' : 'ok'
  }

  return {
    stage,
    state,
    percent,
    remainingMs,
    responseDone,
    resolutionDone,
    responseBreached: sla.response_breached,
    resolutionBreached: sla.resolution_breached,
    responseDue,
    resolutionDue,
    policyHours: Math.round((resolutionDue - created) / 3600000),
  }
}

// Shared icon per health state, used for the headline and the compact badge
// so the same status reads the same way everywhere in the app.
const STATE_ICON = { ok: '🟢', warn: '⚠️', breach: '🔴' }

// One plain-language line summarizing SLA health, for non-technical viewers
// (e.g. "On track", "At risk", "Overdue by 2h", "SLA met").
export function slaHeadline(info) {
  if (!info) return null

  if (info.stage === 'done') {
    return info.state === 'breach'
      ? { text: 'SLA missed', cls: 'breach', icon: STATE_ICON.breach }
      : { text: 'SLA met', cls: 'ok', icon: STATE_ICON.ok }
  }
  if (info.state === 'breach') {
    return { text: `Overdue by ${formatDuration(Math.abs(info.remainingMs))}`, cls: 'breach', icon: STATE_ICON.breach }
  }
  if (info.state === 'warn') {
    return { text: `At risk — ${formatDuration(info.remainingMs)} left`, cls: 'warn', icon: STATE_ICON.warn }
  }
  return { text: `On track — ${formatDuration(info.remainingMs)} left`, cls: 'ok', icon: STATE_ICON.ok }
}

export function slaBadgeInfo(ticket) {
  const info = slaInfo(ticket)
  if (!info) return null
  if (info.stage === 'done') {
    return info.state === 'breach'
      ? { cls: 'sla-breach', icon: STATE_ICON.breach, label: 'Breached' }
      : { cls: 'sla-ok', icon: STATE_ICON.ok, label: 'Met' }
  }
  if (info.state === 'breach') return { cls: 'sla-breach', icon: STATE_ICON.breach, label: `Overdue ${formatDuration(Math.abs(info.remainingMs))}` }
  const cls = info.state === 'warn' ? 'sla-warn' : 'sla-ok'
  return { cls, icon: STATE_ICON[info.state], label: `${formatDuration(info.remainingMs)} left` }
}
