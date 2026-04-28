import { useEffect } from 'react'
import { useDashboardStore } from '../store'

export function useStatePolling(intervalMs: number = 3000) {
  const setPersistedAgents = useDashboardStore((s) => s.setPersistedAgents)
  const setCurrentTask = useDashboardStore((s) => s.setCurrentTask)

  useEffect(() => {
    let mounted = true

    async function fetchState() {
      try {
        const [agentsRes, taskRes] = await Promise.all([
          fetch('/api/state/agents'),
          fetch('/api/state/task'),
        ])
        if (!mounted) return
        const agentsData = await agentsRes.json()
        const taskData = await taskRes.json()
        setPersistedAgents(agentsData.agents || {})
        setCurrentTask(taskData.task || null)
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
  }, [intervalMs, setPersistedAgents, setCurrentTask])
}
