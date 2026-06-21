import { useEffect, useState } from 'react'
import { useDashboardStore } from '../store'

function timeAgo(ts: number): string {
  if (!ts) return ''
  const diff = Math.floor(Date.now() / 1000 - ts)
  if (diff < 5) return 'just now'
  if (diff < 60) return `${diff}s ago`
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  return `${Math.floor(diff / 3600)}h ago`
}

function isWorking(message: string): boolean {
  const idle = ['idle', 'completed', 'finished']
  return !idle.some(k => message.toLowerCase().includes(k))
}

const teamColors: Record<string, string> = {
  planning: 'bg-blue-900/50 text-blue-300',
  engineering_A: 'bg-green-900/50 text-green-300',
  engineering_B: 'bg-emerald-900/50 text-emerald-300',
  engineering: 'bg-green-900/50 text-green-300',
  research: 'bg-cyan-900/50 text-cyan-300',
  validation: 'bg-red-900/50 text-red-300',
}

export default function WorkerStatus() {
  const workerStatuses = useDashboardStore((s) => s.workerStatuses)
  const [, setTick] = useState(0)

  // Re-render every 5s to update "time ago" labels
  useEffect(() => {
    const interval = setInterval(() => setTick(t => t + 1), 5000)
    return () => clearInterval(interval)
  }, [])

  const entries = Object.values(workerStatuses)

  if (entries.length === 0) {
    return (
      <div className="text-gray-600 text-sm text-center py-8">
        No worker status reports yet.
        <br />
        <span className="text-xs">Status updates appear when workers are active.</span>
      </div>
    )
  }

  // Sort: working entries first, then by timestamp desc
  const sorted = [...entries].sort((a, b) => {
    const aWorking = isWorking(a.message) ? 0 : 1
    const bWorking = isWorking(b.message) ? 0 : 1
    if (aWorking !== bWorking) return aWorking - bWorking
    return b.timestamp - a.timestamp
  })

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
      {sorted.map((ws) => {
        const working = isWorking(ws.message)
        return (
          <div
            key={ws.agent}
            className={`
              rounded-lg border p-3 transition-colors duration-300
              ${working
                ? 'border-green-500/30 bg-green-900/10'
                : 'border-white/5 bg-white/[0.02]'
              }
            `}
          >
            <div className="flex items-center gap-2 mb-2">
              <span
                className={`w-2 h-2 rounded-full flex-shrink-0 ${
                  working ? 'bg-green-400 animate-pulse' : 'bg-gray-600'
                }`}
              />
              <span className="font-medium text-sm text-white truncate">{ws.agent}</span>
              {ws.team && (
                <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${teamColors[ws.team] || 'bg-gray-800 text-gray-400'}`}>
                  {ws.team}
                </span>
              )}
            </div>
            <div className={`text-sm ${working ? 'text-gray-300' : 'text-gray-500'} mb-1`}>
              {ws.message}
            </div>
            {timeAgo(ws.timestamp) && (
              <div className="text-[10px] text-gray-600">
                {timeAgo(ws.timestamp)}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
