import { useDashboardStore } from '../store'

const statusColors: Record<string, string> = {
  idle: 'var(--status-idle)',
  running: 'var(--status-running)',
  done: 'var(--status-done)',
  error: 'var(--status-error)',
}

interface AgentNode {
  name: string
  model: string
  vision?: boolean
  status?: string
}

function AgentRow({ agent, depth }: { agent: AgentNode; depth: number }) {
  const agentStatuses = useDashboardStore((s) => s.agentStatuses)
  const persistedAgents = useDashboardStore((s) => s.persistedAgents)
  const status = agentStatuses[agent.name] || agent.status || 'idle'
  const persisted = persistedAgents[agent.name]
  const isRunning = status === 'running'

  return (
    <div
      className={`flex items-center gap-2 py-1.5 px-2 text-sm rounded cursor-pointer min-h-[32px] md:min-h-0 md:py-1 ${isRunning ? 'bg-green-900/20' : 'hover:bg-white/5'}`}
      style={{ paddingLeft: `${depth * 16 + 8}px` }}
    >
      <span
        className="w-2.5 h-2.5 rounded-full flex-shrink-0"
        style={{ backgroundColor: statusColors[status] || statusColors.idle }}
      />
      <div className="flex flex-col min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <span className="truncate text-white">{agent.name}</span>
          <span className="text-xs text-gray-600 truncate max-w-20">
            {agent.model.split('/').pop()}
          </span>
        </div>
        {(isRunning || persisted?.last_message) && (
          <span className="text-xs text-gray-500 truncate">
            {isRunning ? 'Running...' : persisted?.last_message?.slice(0, 60)}
          </span>
        )}
      </div>
      <span className={`text-xs ml-auto flex-shrink-0 ${status === 'running' ? 'text-green-400' : status === 'done' ? 'text-blue-400' : status === 'error' ? 'text-red-400' : 'text-gray-600'}`}>
        {status}
      </span>
      {agent.vision && <span className="text-xs text-purple-400 flex-shrink-0">👁</span>}
    </div>
  )
}

export default function Sidebar() {
  const teamData = useDashboardStore((s) => s.teamData)

  if (!teamData) return <div className="p-4 text-gray-600 text-sm">Connecting...</div>

  return (
    <div className="p-2">
      <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider px-2 mb-2">
        Your Agent Teams
      </h3>
      <div className="mb-3">
        <div className="flex items-center gap-2 px-2 py-1 text-sm bg-orange-900/20 rounded mb-1">
          <span className="text-orange-400 text-xs">You</span>
        </div>
        <AgentRow agent={teamData.orchestrator} depth={1} />
      </div>
      {teamData.teams.map(team => (
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
