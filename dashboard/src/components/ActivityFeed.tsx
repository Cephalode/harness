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
        <div
          key={i}
          className="
            /* Mobile: vertical card layout */
            flex flex-col gap-1 px-3 py-2.5 rounded border-b border-white/5
            bg-white/[0.02]
            /* Desktop: horizontal layout */
            md:flex-row md:items-start md:gap-3 md:px-2 md:py-1.5 md:border-b-0
            md:bg-transparent md:rounded md:hover:bg-white/[0.03]
          "
        >
          {/* Timestamp: badge on mobile, inline on desktop */}
          <span
            className="text-xs text-gray-500 md:text-gray-600 md:mt-0.5 md:flex-shrink-0 md:w-16"
          >
            <span className="md:hidden inline-block bg-white/5 rounded px-1.5 py-0.5 text-[10px] font-mono">
              {formatTimestamp(event.timestamp)}
            </span>
            <span className="hidden md:inline">
              {formatTimestamp(event.timestamp)}
            </span>
          </span>

          {/* Label + agent/team row */}
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs font-medium" style={{ color: eventColor(event.type) }}>
              {eventLabel(event.type)}
            </span>
            <span className="text-sm text-gray-400">
              {event.agent && <span className="text-blue-400">{event.agent}</span>}
              {event.team && <span className="text-gray-600"> → </span>}
              {event.team && <span className="text-yellow-400">{event.team}</span>}
            </span>
          </div>

          {/* Message preview: full width on mobile, truncated inline on desktop */}
          {event.data?.message != null && (
            <span className="text-xs text-gray-600 md:truncate md:ml-2">
              {String(event.data.message as string).slice(0, 120)}
            </span>
          )}
        </div>
      ))}
    </div>
  )
}
