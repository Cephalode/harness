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

// --- Layout constants ---
const NODE_WIDTH = 160
const NODE_HEIGHT = 80
const LEVEL_GAP = 250 // horizontal gap between hierarchy levels
const NODE_GAP = 20 // vertical gap between sibling nodes
const TEAM_GAP = 60 // extra vertical gap between teams

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

/**
 * Manual left-to-right layout algorithm.
 *
 * Columns (X axis) represent hierarchy depth:
 *   col 0 → Orchestrator
 *   col 1 → Team Leads
 *   col 2 → Workers
 *
 * Rows (Y axis) spread nodes within the same level.
 * Each team is allocated a vertical slice tall enough for all its workers,
 * and teams are stacked with TEAM_GAP between them. The orchestrator is
 * centered vertically relative to all teams.
 */
function buildGraph(
  teamData: ReturnType<typeof useDashboardStore.getState>['teamData'],
  agentStatuses: Record<string, string>,
): { nodes: Node[]; edges: Edge[] } {
  if (!teamData) return { nodes: [], edges: [] }

  const nodes: Node[] = []
  const edges: Edge[] = []

  const teams = teamData.teams
  const teamCount = teams.length

  // Column X positions
  const col0 = 0 // orchestrator
  const col1 = LEVEL_GAP // leads
  const col2 = LEVEL_GAP * 2 // workers

  // Step 1: Calculate the vertical height each team needs.
  // A team's height is determined by its workers column.
  const teamHeights = teams.map((team) => {
    const workerCount = team.workers.length
    if (workerCount === 0) return NODE_HEIGHT
    return workerCount * NODE_HEIGHT + (workerCount - 1) * NODE_GAP
  })

  // Total diagram height = sum of team heights + gaps between teams
  const totalHeight =
    teamHeights.reduce((sum, h) => sum + h, 0) + (teamCount - 1) * TEAM_GAP

  // Step 2: Calculate Y offsets for each team (cumulative).
  const teamYOffsets: number[] = []
  let runningY = 0
  for (let i = 0; i < teamCount; i++) {
    teamYOffsets.push(runningY)
    runningY += teamHeights[i] + TEAM_GAP
  }

  // Step 3: Place the orchestrator, centered vertically.
  const orchStatus = agentStatuses[teamData.orchestrator.name] || 'idle'
  const orchY = Math.max(0, (totalHeight - NODE_HEIGHT) / 2)
  nodes.push({
    id: 'orchestrator',
    type: 'agent',
    position: { x: col0, y: orchY },
    data: {
      label: teamData.orchestrator.name,
      model: teamData.orchestrator.model,
      status: orchStatus,
      role: 'orchestrator',
    },
  })

  // Step 4: For each team, place the lead and its workers.
  teams.forEach((team, ti) => {
    const teamId = `team-${team.name}`
    const teamTop = teamYOffsets[ti]
    const teamHeight = teamHeights[ti]

    // Lead is centered vertically within the team's allocated space
    const leadY = teamTop + (teamHeight - NODE_HEIGHT) / 2
    const leadStatus = agentStatuses[team.lead.name] || 'idle'

    nodes.push({
      id: teamId,
      type: 'agent',
      position: { x: col1, y: leadY },
      data: {
        label: team.lead.name,
        model: team.lead.model,
        status: leadStatus,
        role: 'lead',
      },
    })

    // Edge: orchestrator → lead
    edges.push({
      id: `orch-${team.name}`,
      source: 'orchestrator',
      target: teamId,
      animated: leadStatus === 'running',
      style: { stroke: '#4a4a6a', strokeWidth: 2 },
      markerEnd: { type: MarkerType.ArrowClosed, color: '#4a4a6a' },
    })

    // Workers: evenly spaced within the team's vertical space
    team.workers.forEach((worker, wi) => {
      const workerId = `worker-${team.name}-${worker.name}`
      const workerStatus = agentStatuses[worker.name] || 'idle'

      const workerY = teamTop + wi * (NODE_HEIGHT + NODE_GAP)

      nodes.push({
        id: workerId,
        type: 'agent',
        position: { x: col2, y: workerY },
        data: {
          label: worker.name,
          model: worker.model,
          status: workerStatus,
          vision: worker.vision,
          role: 'worker',
        },
      })

      // Edge: lead → worker
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
