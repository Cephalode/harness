import { useEffect } from 'react'
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
  type NodeTypes,
  MarkerType,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { useDashboardStore } from '../store'

// Custom node component for agents
function AgentNodeComponent({ data }: { data: { label: string; model: string; status: string; vision?: boolean; role: string } }) {
  const statusColors: Record<string, string> = {
    idle: '#fbbf24',
    running: '#4ade80',
    done: '#60a5fa',
    error: '#ef4444',
  }
  const roleColors: Record<string, string> = {
    orchestrator: '#f97316',
    lead: '#3b82f6',
    worker: '#8b5cf6',
  }
  const borderColor = statusColors[data.status] || statusColors.idle
  const bgColor = roleColors[data.role] || '#1a1a2e'

  return (
    <div
      className="px-4 py-2 rounded-lg text-xs"
      style={{
        background: bgColor + '33',
        border: `2px solid ${borderColor}`,
        minWidth: 140,
      }}
    >
      <div className="font-semibold text-white truncate">{data.label}</div>
      <div className="text-gray-400 truncate">{data.model.split('/').pop()}</div>
      <div className="flex items-center gap-1 mt-1">
        <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: borderColor }} />
        <span className="text-gray-500">{data.status}</span>
        {data.vision && <span className="text-purple-400 ml-1">👁</span>}
      </div>
    </div>
  )
}

const nodeTypes: NodeTypes = {
  agent: AgentNodeComponent as never,
}

// Layout positions for the hierarchy
function buildGraph(
  teamData: ReturnType<typeof useDashboardStore.getState>['teamData'],
  agentStatuses: Record<string, string>,
): { nodes: Node[]; edges: Edge[] } {
  if (!teamData) return { nodes: [], edges: [] }

  const nodes: Node[] = []
  const edges: Edge[] = []

  // Orchestrator at top center
  const orchStatus = agentStatuses[teamData.orchestrator.name] || 'idle'
  nodes.push({
    id: 'orchestrator',
    type: 'agent',
    position: { x: 400, y: 50 },
    data: {
      label: teamData.orchestrator.name,
      model: teamData.orchestrator.model,
      status: orchStatus,
      role: 'orchestrator',
    },
  })

  const teamCount = teamData.teams.length
  const teamSpacing = 300
  const startX = 400 - ((teamCount - 1) * teamSpacing) / 2

  teamData.teams.forEach((team, ti) => {
    const teamX = startX + ti * teamSpacing
    const teamId = `team-${team.name}`

    // Lead node
    const leadStatus = agentStatuses[team.lead.name] || 'idle'
    nodes.push({
      id: teamId,
      type: 'agent',
      position: { x: teamX, y: 200 },
      data: {
        label: team.lead.name,
        model: team.lead.model,
        status: leadStatus,
        role: 'lead',
      },
    })

    // Edge: orchestrator -> lead
    edges.push({
      id: `orch-${team.name}`,
      source: 'orchestrator',
      target: teamId,
      animated: leadStatus === 'running',
      style: { stroke: '#4a4a6a', strokeWidth: 2 },
      markerEnd: { type: MarkerType.ArrowClosed, color: '#4a4a6a' },
    })

    // Worker nodes
    const workerSpacing = 160
    const workersStartX = teamX - ((team.workers.length - 1) * workerSpacing) / 2

    team.workers.forEach((worker, wi) => {
      const workerId = `worker-${worker.name}`
      const workerStatus = agentStatuses[worker.name] || 'idle'
      nodes.push({
        id: workerId,
        type: 'agent',
        position: { x: workersStartX + wi * workerSpacing, y: 350 },
        data: {
          label: worker.name,
          model: worker.model,
          status: workerStatus,
          vision: worker.vision,
          role: 'worker',
        },
      })

      // Edge: lead -> worker
      edges.push({
        id: `${team.name}-${worker.name}`,
        source: teamId,
        target: workerId,
        animated: workerStatus === 'running',
        style: { stroke: '#3a3a5a', strokeWidth: 1.5 },
        markerEnd: { type: MarkerType.ArrowClosed, color: '#3a3a5a' },
      })
    })
  })

  return { nodes, edges }
}

export default function SystemDiagram() {
  const teamData = useDashboardStore((s) => s.teamData)
  const agentStatuses = useDashboardStore((s) => s.agentStatuses)
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([])

  useEffect(() => {
    const { nodes: newNodes, edges: newEdges } = buildGraph(teamData, agentStatuses)
    setNodes(newNodes)
    setEdges(newEdges)
  }, [teamData, agentStatuses, setNodes, setEdges])

  if (!teamData) {
    return (
      <div className="flex items-center justify-center h-full text-gray-600 text-sm">
        Waiting for team data...
      </div>
    )
  }

  return (
    <div className="w-full h-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.3 }}
        proOptions={{ hideAttribution: true }}
        style={{ background: 'var(--bg-primary)' }}
      >
        <Background color="#1a1a2e" gap={20} size={1} />
        <Controls
          style={{ background: 'var(--bg-sidebar)', borderColor: 'var(--border)' }}
        />
        <MiniMap
          style={{ background: 'var(--bg-sidebar)', borderColor: 'var(--border)' }}
          nodeColor={() => '#3b82f6'}
        />
      </ReactFlow>
    </div>
  )
}
