import { useEffect } from 'react'
import { useDashboardStore } from '../store'

export default function StatusBar() {
  const costs = useDashboardStore((s) => s.costs)
  const session = useDashboardStore((s) => s.session)
  const events = useDashboardStore((s) => s.events)

  // Poll costs periodically
  useEffect(() => {
    const fetchCosts = () => {
      fetch('/api/costs')
        .then(r => r.json())
        .then(data => useDashboardStore.getState().setCosts(data))
        .catch(() => {})
    }
    const fetchSession = () => {
      fetch('/api/session')
        .then(r => r.json())
        .then(data => useDashboardStore.getState().setSession(data))
        .catch(() => {})
    }
    fetchCosts()
    fetchSession()
    const interval = setInterval(() => { fetchCosts(); fetchSession() }, 5000)
    return () => clearInterval(interval)
  }, [])

  const cost = costs?.total_cost ?? 0
  const inTok = costs?.total_usage?.input_tokens ?? 0
  const outTok = costs?.total_usage?.output_tokens ?? 0

  return (
    <footer className="flex items-center justify-between px-4 py-1.5 text-xs border-t"
            style={{ borderColor: 'var(--border)', background: 'var(--bg-sidebar)' }}>
      <div className="flex items-center gap-4 text-gray-500">
        <span>Session: {session?.session_id?.slice(0, 8) ?? '---'}</span>
        <span>Events: {events.length}</span>
      </div>
      <div className="flex items-center gap-4 text-gray-500">
        <span>Cost: ${cost.toFixed(4)}</span>
        <span>Tokens: {inTok.toLocaleString()} in / {outTok.toLocaleString()} out</span>
      </div>
    </footer>
  )
}
