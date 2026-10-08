import { useEffect, useRef } from 'react'

const WS_BASE = 'ws://localhost:8000'

// Opens a WebSocket at `path` (e.g. `/ws/tickets/5`) authenticated with the
// stored JWT, and calls `onMessage(parsedEvent)` for every message. Reconnects
// with a short fixed backoff on drop/error. `enabled` lets callers defer
// connecting until they have what they need (e.g. an id from the route).
// `onStatusChange(connected)` is optional, for a "live" indicator in the UI.
export default function useWebSocket(path, onMessage, enabled = true, onStatusChange) {
  const onMessageRef = useRef(onMessage)
  onMessageRef.current = onMessage
  const onStatusRef = useRef(onStatusChange)
  onStatusRef.current = onStatusChange

  useEffect(() => {
    if (!enabled || !path) return undefined

    const token = localStorage.getItem('token')
    if (!token) return undefined

    let socket
    let closedByEffect = false
    let retryTimer

    function connect() {
      socket = new WebSocket(`${WS_BASE}${path}?token=${encodeURIComponent(token)}`)
      socket.onopen = () => onStatusRef.current?.(true)
      socket.onmessage = (event) => {
        try {
          onMessageRef.current(JSON.parse(event.data))
        } catch {
          // ignore malformed frames
        }
      }
      socket.onclose = () => {
        onStatusRef.current?.(false)
        if (!closedByEffect) {
          retryTimer = setTimeout(connect, 2000)
        }
      }
      socket.onerror = () => socket.close()
    }

    connect()

    return () => {
      closedByEffect = true
      clearTimeout(retryTimer)
      socket?.close()
    }
  }, [path, enabled])
}
