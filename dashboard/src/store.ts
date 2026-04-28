import { create } from 'zustand'

// Event types matching backend HarnessEvent
export interface HarnessEvent {
  type: string
  agent: string | null
  team: string | null
  data: Record<string, unknown>
  timestamp: number
}

export interface AgentNode {
  name: string
  model: string
  vision?: boolean
  status: string
}

export interface WorkerStatusEntry {
  agent: string
  message: string
  timestamp: number
  team: string | null
  task: string | null
}

export interface TeamNode {
  name: string
  color: string
  lead: AgentNode
  workers: AgentNode[]
}

export interface TeamData {
  orchestrator: AgentNode
  teams: TeamNode[]
}

export interface CostData {
  total_cost: number
  total_usage: { input_tokens: number; output_tokens: number }
  by_agent: Record<string, number>
  by_team: Record<string, number>
}

export interface PersistedAgentState {
  name: string
  status: string
  model: string
  team: string | null
  last_message: string
  last_updated: number
}

export interface TaskState {
  task: string
  platform: string
  started_at: number
  status: string
}

export interface QueueStatus {
  queue_length: number
  is_processing: boolean
  current_task: {
    task_id: string
    message: string
    status: string
    started_at: number
  } | null
  total_processed: number
}

export interface SessionData {
  session_id: string
  message_count: number
  created_at: string
}

interface DashboardState {
  // Connection
  connected: boolean

  // Team tree
  teamData: TeamData | null

  // Events
  events: HarnessEvent[]
  maxEvents: number  // circular buffer size

  // Costs
  costs: CostData | null

  // Session
  session: SessionData | null

 // Agent status tracking (agent_name -> status)
 agentStatuses: Record<string, string>

  // Worker status tracking (agent_name -> WorkerStatusEntry)
  workerStatuses: Record<string, WorkerStatusEntry>

  // Persisted agent state from StateStore REST API
  persistedAgents: Record<string, PersistedAgentState>

  // Current task from StateStore REST API
  currentTask: TaskState | null

  // Queue status from async task queue
  queueStatus: QueueStatus | null

 // Actions
  setConnected: (connected: boolean) => void
  setTeamData: (data: TeamData) => void
  addEvent: (event: HarnessEvent) => void
  setCosts: (costs: CostData) => void
  setSession: (session: SessionData) => void
 updateAgentStatus: (agent: string, status: string) => void
  setWorkerStatuses: (statuses: Record<string, WorkerStatusEntry>) => void
  updateWorkerStatus: (agent: string, status: WorkerStatusEntry) => void
  setPersistedAgents: (agents: Record<string, PersistedAgentState>) => void
  setCurrentTask: (task: TaskState | null) => void
  setQueueStatus: (status: QueueStatus) => void
  clearEvents: () => void
}

const MAX_EVENTS = 500

export const useDashboardStore = create<DashboardState>((set) => ({
  connected: false,
  teamData: null,
  events: [],
  maxEvents: MAX_EVENTS,
  costs: null,
  session: null,
  agentStatuses: {},
 workerStatuses: {},
  persistedAgents: {},
  currentTask: null,
  queueStatus: null,

  setConnected: (connected) => set({ connected }),
  setTeamData: (teamData) => set({ teamData }),
  addEvent: (event) => set((state) => {
    const events = [...state.events, event]
    if (events.length > state.maxEvents) {
      events.splice(0, events.length - state.maxEvents)
    }
    // Derive agent status from event
    const statuses = { ...state.agentStatuses }
    if (event.agent) {
      if (event.type === 'agent_start') statuses[event.agent] = 'running'
      else if (event.type === 'agent_end') statuses[event.agent] = 'done'
      else if (event.type === 'agent_error') statuses[event.agent] = 'error'
    }
    // Derive worker status from event
    let workerStatuses = state.workerStatuses
    if (event.type === 'worker_status' && event.agent) {
      workerStatuses = { ...state.workerStatuses }
      workerStatuses[event.agent] = {
        agent: event.agent,
        message: (event.data.message as string) || 'Working...',
        timestamp: event.timestamp,
        team: event.team,
        task: (event.data.task as string) || null,
      }
    }
    return { events, agentStatuses: statuses, workerStatuses }
  }),
  setCosts: (costs) => set({ costs }),
  setSession: (session) => set({ session }),
 updateAgentStatus: (agent, status) => set((state) => ({
   agentStatuses: { ...state.agentStatuses, [agent]: status },
 })),
 setWorkerStatuses: (workerStatuses) => set({ workerStatuses }),
 updateWorkerStatus: (agent, status) => set((state) => ({
   workerStatuses: { ...state.workerStatuses, [agent]: status },
 })),
  setPersistedAgents: (persistedAgents) => set({ persistedAgents }),
  setCurrentTask: (currentTask) => set({ currentTask }),
  setQueueStatus: (queueStatus) => set({ queueStatus }),
  clearEvents: () => set({ events: [] }),
}))
