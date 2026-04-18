import { useEffect, useRef } from 'react'
import { useDashboardStore } from '../store'

function formatTimestamp(ts: number): string {
  const d = new Date(ts * 1000)
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function eventLabel(type: string): string {
  const labels: Record<string, string> = {
    session_start: '🚀 Session Started',
    session_end: '✅ Session Complete',
    routing: '🔀 Routing',
    team_start: '▶️ Team Started',
    team_done: '🏁 Team Complete',
    agent_start: '⚡ Agent Started',
    agent_end: '✓ Agent Finished',
    agent_error: '❌ Agent Error',
  }
  return labels[type] || type
}

function eventColor(type: string): string {
  if (type.includes('error')) return 'var(--status-error)'
  if (type.includes('start')) return 'var(--status-running)'
  if (type.includes('end') || type.includes('done')) return 'var(--status-done)'
  return 'var(--text-dim)'
}

export default function ActivityFeed() {
  const events = useDashboardStore((s) => s.events)
  const scrollRef = useRef<HTMLDivElement>(null)

  // Auto-scroll to bottom on new events
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [events.length])

  if (events.length === 0) {
    return (
      <div className="text-gray-600 text-sm text-center py-8">
        Waiting for agent activity...
        <br />
        <span className="text-xs">Send a message below to start.</span>
      </div>
    )
  }

  return (
    <div ref={scrollRef} className="space-y-2 overflow-y-auto">
      {events.map((event, i) => (
        <div key={i} className="flex items-start gap-3 px-2 py-1.5 rounded hover:bg-white/3">
          <span className="text-xs text-gray-600 mt-0.5 flex-shrink-0 w-16">
            {formatTimestamp(event.timestamp)}
          </span>
          <span className="text-xs font-medium mt-0.5" style={{ color: eventColor(event.type) }}>
            {eventLabel(event.type)}
          </span>
          <span className="text-sm text-gray-400">
            {event.agent && <span className="text-blue-400">{event.agent}</span>}
            {event.team && <span className="text-gray-600"> → </span>}
            {event.team && <span className="text-yellow-400">{event.team}</span>}
          </span>
          {event.data?.message != null && (
            <span className="text-xs text-gray-600 truncate ml-2">
              {String(event.data.message as string).slice(0, 120)}
            </span>
          )}
        </div>
      ))}
    </div>
  )
}
