import { useState, useEffect } from 'react'

interface AgentNode {
  name: string
  model: string
  vision?: boolean
  status?: string
}

interface TeamNode {
  name: string
  color: string
  lead: AgentNode
  workers: AgentNode[]
}

interface TeamData {
  orchestrator: AgentNode
  teams: TeamNode[]
}

const statusColors: Record<string, string> = {
  idle: 'var(--status-idle)',
  running: 'var(--status-running)',
  done: 'var(--status-done)',
  error: 'var(--status-error)',
}

function AgentRow({ agent, depth }: { agent: AgentNode; depth: number }) {
  const status = agent.status || 'idle'
  return (
    <div className="flex items-center gap-2 py-1 px-2 text-sm hover:bg-white/5 rounded cursor-pointer"
         style={{ paddingLeft: `${depth * 16 + 8}px` }}>
      <span className="w-2 h-2 rounded-full flex-shrink-0"
            style={{ backgroundColor: statusColors[status] || statusColors.idle }} />
      <span className="truncate">{agent.name}</span>
      {agent.vision && <span className="text-xs text-purple-400 ml-auto">👁</span>}
      <span className="text-xs text-gray-600 ml-auto truncate max-w-20">{agent.model.split('/').pop()}</span>
    </div>
  )
}

export default function Sidebar() {
  const [data, setData] = useState<TeamData | null>(null)

  useEffect(() => {
    fetch('/api/teams')
      .then(r => r.json())
      .then(setData)
      .catch(() => {})
  }, [])

  if (!data) return <div className="p-4 text-gray-600 text-sm">Loading teams...</div>

  return (
    <div className="p-2">
      <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider px-2 mb-2">
        Your Agent Teams
      </h3>
      <div className="mb-3">
        <div className="flex items-center gap-2 px-2 py-1 text-sm bg-orange-900/20 rounded mb-1">
          <span className="text-orange-400 text-xs">You</span>
        </div>
        <AgentRow agent={data.orchestrator} depth={1} />
      </div>
      {data.teams.map(team => (
        <div key={team.name} className="mb-2">
          <div className="text-xs text-gray-600 uppercase tracking-wider px-2 mt-2 mb-1">
            {team.name}
          </div>
          <AgentRow agent={team.lead} depth={1} />
          {team.workers.map(w => (
            <AgentRow key={w.name} agent={w} depth={2} />
          ))}
        </div>
      ))}
    </div>
  )
}
