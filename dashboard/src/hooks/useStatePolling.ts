import { useEffect } from 'react'
import { useDashboardStore } from '../store'

export function useStatePolling(intervalMs: number = 3000) {
  const setPersistedAgents = useDashboardStore((s) => s.setPersistedAgents)
  const setCurrentTask = useDashboardStore((s) => s.setCurrentTask)
  const setQueueStatus = useDashboardStore((s) => s.setQueueStatus)

  useEffect(() => {
    let mounted = true

    async function fetchState() {
      try {
        const [agentsRes, taskRes, queueRes] = await Promise.all([
          fetch('/api/state/agents'),
          fetch('/api/state/task'),
          fetch('/api/queue'),
        ])
        if (!mounted) return
        const agentsData = await agentsRes.json()
        const taskData = await taskRes.json()
        const queueData = await queueRes.json()
        setPersistedAgents(agentsData.agents || {})
        setCurrentTask(taskData.task || null)
        setQueueStatus(queueData)
      } catch {
        // Silently ignore fetch errors (server may not be running)
      }
    }

    fetchState()
    const id = setInterval(fetchState, intervalMs)
    return () => {
      mounted = false
      clearInterval(id)
    }
  }, [intervalMs, setPersistedAgents, setCurrentTask, setQueueStatus])
}
