import { useState, useEffect, useRef, useCallback } from 'react'
import { useDashboardStore } from '../store'

type TaskPhase = 'idle' | 'queued' | 'running' | 'completed' | 'failed'

interface PendingTask {
  taskId: string
  phase: TaskPhase
  position: number | null
  result: string | null
}

export default function MessageInput() {
  const [message, setMessage] = useState('')
  const [pending, setPending] = useState<PendingTask | null>(null)
  const queueStatus = useDashboardStore((s) => s.queueStatus)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Clean up polling on unmount
  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [])

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }, [])

  const startPolling = useCallback((taskId: string) => {
    stopPolling()
    pollRef.current = setInterval(async () => {
      try {
        const res = await fetch(`/api/task/${taskId}`)
        const data = await res.json()
        if (data.status === 'completed') {
          setPending((p) => p ? { ...p, phase: 'completed', result: data.result || 'Done' } : null)
          stopPolling()
          // Auto-clear completed after 5s
          setTimeout(() => setPending(null), 5000)
        } else if (data.status === 'failed') {
          setPending((p) => p ? { ...p, phase: 'failed', result: data.error || 'Task failed' } : null)
          stopPolling()
          setTimeout(() => setPending(null), 8000)
        } else if (data.status === 'running') {
          setPending((p) => p ? { ...p, phase: 'running', position: null } : null)
        } else {
          // still queued — try to get position from queue status
          setPending((p) => p ? { ...p, phase: 'queued' } : null)
        }
      } catch {
        // ignore transient errors
      }
    }, 2000)
  }, [stopPolling])

  const handleSend = async () => {
    if (!message.trim() || pending) return
    const msg = message
    setMessage('')
    try {
      const res = await fetch('/api/message', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: msg }),
      })
      const data = await res.json()
      if (data.task_id) {
        setPending({ taskId: data.task_id, phase: 'queued', position: data.position ?? null, result: null })
        startPolling(data.task_id)
      }
    } catch (err) {
      console.error('Failed to send message:', err)
    }
  }

  const isDisabled = !!pending
  const queueBadge = queueStatus && queueStatus.queue_length > 0 ? queueStatus.queue_length : null

  return (
    <div className="border-t px-3 py-2 md:px-4 md:py-3" style={{ borderColor: 'var(--border)', background: 'var(--bg-sidebar)' }}>
      {/* Pending task status bar */}
      {pending && (
        <div className="mb-2 px-3 py-1.5 rounded text-xs flex items-center justify-between" style={{ background: 'var(--bg-primary)', border: '1px solid var(--border)' }}>
          <span style={{ color: pending.phase === 'failed' ? 'var(--status-error)' : pending.phase === 'completed' ? 'var(--status-done)' : 'var(--status-running)' }}>
            {pending.phase === 'queued' && `⏳ Queued${pending.position ? ` (position ${pending.position})` : ''}...`}
            {pending.phase === 'running' && '⚡ Processing...'}
            {pending.phase === 'completed' && `✅ ${pending.result}`}
            {pending.phase === 'failed' && `❌ ${pending.result}`}
          </span>
          {(pending.phase === 'completed' || pending.phase === 'failed') && (
            <button onClick={() => setPending(null)} className="text-gray-500 hover:text-gray-300 ml-2">✕</button>
          )}
        </div>
      )}
      <div className="flex gap-2">
        <input
          type="text"
          value={message}
          onChange={e => setMessage(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && !isDisabled && handleSend()}
          placeholder={isDisabled ? 'Task in progress...' : 'Send a message to the orchestrator...'}
          disabled={isDisabled}
          className="flex-1 px-3 py-2 rounded text-sm outline-none min-h-[44px]"
          style={{ background: 'var(--bg-primary)', color: 'var(--text-primary)', border: '1px solid var(--border)', opacity: isDisabled ? 0.6 : 1 }}
        />
        <button
          onClick={handleSend}
          disabled={isDisabled}
          className="px-4 py-2 rounded text-sm font-medium min-h-[44px] min-w-[44px] flex items-center justify-center relative"
          style={{ background: isDisabled ? 'var(--border)' : 'var(--accent-blue)', color: 'var(--text-primary)', opacity: isDisabled ? 0.6 : 1 }}
        >
          <span className="md:hidden">{queueBadge ? `↑${queueBadge}` : '↑'}</span>
          <span className="hidden md:inline">
            {queueBadge ? `Send (${queueBadge})` : 'Send'}
          </span>
        </button>
      </div>
    </div>
  )
}
