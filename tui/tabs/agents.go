package tabs

import (
	"fmt"
	"sort"
	"strings"

	"github.com/cephalode/harness-tui/api"

	"github.com/charmbracelet/bubbles/viewport"
	"github.com/charmbracelet/lipgloss"
)

var (
	idleStyle     = lipgloss.NewStyle().Foreground(lipgloss.Color("#888888"))
	runningStyle  = lipgloss.NewStyle().Foreground(lipgloss.Color("#50FA7B")).Bold(true)
	doneStyle     = lipgloss.NewStyle().Foreground(lipgloss.Color("#8BE9FD"))
	errStyle      = lipgloss.NewStyle().Foreground(lipgloss.Color("#FF5555"))
	queuedStyle   = lipgloss.NewStyle().Foreground(lipgloss.Color("#FFB86C"))

	headerStyle   = lipgloss.NewStyle().Bold(true).Foreground(lipgloss.Color("#7D56F4"))
	dimStyle      = lipgloss.NewStyle().Foreground(lipgloss.Color("#555555"))
)

// AgentsTab shows a grid of all agents with status, model, and team info.
type AgentsTab struct {
	Viewport viewport.Model
	agents   map[string]api.AgentState
	teams    *api.TeamInfo
	workers  []api.WorkerStatus
	width    int
	height   int
}

func NewAgentsTab() *AgentsTab {
	vp := viewport.New(80, 20)
	return &AgentsTab{
		Viewport: vp,
	}
}

func (t *AgentsTab) SetSize(width, height int) {
	t.width = width
	t.height = height
	t.Viewport.Width = width
	t.Viewport.Height = height
}

func (t *AgentsTab) SetAgents(agents map[string]api.AgentState) {
	t.agents = agents
	t.render()
}

func (t *AgentsTab) SetTeams(teams *api.TeamInfo) {
	t.teams = teams
	t.render()
}

func (t *AgentsTab) SetWorkerStatuses(workers []api.WorkerStatus) {
	t.workers = workers
	t.render()
}

func (t *AgentsTab) UpdateFromEvent(e api.HarnessEvent) {
	// Live status updates from event stream
	if t.agents == nil {
		t.agents = make(map[string]api.AgentState)
	}
	if e.Agent == "" {
		return
	}
	state, ok := t.agents[e.Agent]
	if !ok {
		state = api.AgentState{Name: e.Agent}
	}
	switch e.Type {
	case "agent_start":
		state.Status = "running"
		if m, ok := e.Data["model"].(string); ok {
			state.Model = m
		}
		if tm, ok := e.Data["team"].(string); ok {
			state.Team = tm
		}
	case "agent_end":
		if s, ok := e.Data["status"].(string); ok && s == "error" {
			state.Status = "error"
		} else {
			state.Status = "done"
		}
	case "agent_error":
		state.Status = "error"
	}
	t.agents[e.Agent] = state
	t.render()
}

func (t *AgentsTab) render() {
	var b strings.Builder

	if t.teams != nil {
		// Render team tree structure
		orch := t.teams.Orchestrator
		fmt.Fprintf(&b, "%s\n", headerStyle.Render("Orchestrator"))
		b.WriteString(t.renderAgentLine("  ", orch.Name, orch.Model, orch.Status, ""))
		b.WriteString("\n")

		for _, team := range t.teams.Teams {
			color := team.Color
			teamHeader := fmt.Sprintf("Team: %s", team.Name)
			if color != "" {
				teamHeader = lipgloss.NewStyle().Bold(true).Foreground(lipgloss.Color("#"+color)).Render(teamHeader)
			} else {
				teamHeader = headerStyle.Render(teamHeader)
			}
			fmt.Fprintf(&b, "\n%s\n", teamHeader)

			// Lead
			b.WriteString(t.renderAgentLine("  ├── ", team.Lead.Name, team.Lead.Model, t.agentStatus(team.Lead.Name), ""))

			// Workers
			for i, w := range team.Workers {
				prefix := "  │   "
				if i == len(team.Workers)-1 {
					prefix = "  └── "
				}
				wStatus := t.agentStatus(w.Name)
				wMsg := t.workerMessage(w.Name)
				b.WriteString(t.renderAgentLine(prefix, w.Name, w.Model, wStatus, wMsg))
			}
		}
	} else if t.agents != nil {
		// Fallback: flat agent list from state
		fmt.Fprintf(&b, "%s\n", headerStyle.Render("Agents"))
		names := make([]string, 0, len(t.agents))
		for n := range t.agents {
			names = append(names, n)
		}
		sort.Strings(names)
		for _, name := range names {
			a := t.agents[name]
			b.WriteString(t.renderAgentLine("  ", name, a.Model, a.Status, ""))
		}
	} else {
		b.WriteString(dimStyle.Render("No agent data yet..."))
	}

	t.Viewport.SetContent(b.String())
}

func (t *AgentsTab) renderAgentLine(prefix, name, model, status, extra string) string {
	statusStr := statusIcon(status)
	modelStr := ""
	if model != "" {
		modelStr = dimStyle.Render(fmt.Sprintf(" [%s]", shortModel(model)))
	}
	extraStr := ""
	if extra != "" {
		extraStr = dimStyle.Render(" — " + extra)
	}
	return fmt.Sprintf("%s%s %s%s%s\n", prefix, statusStr, name, modelStr, extraStr)
}

func (t *AgentsTab) agentStatus(name string) string {
	if t.agents != nil {
		if a, ok := t.agents[name]; ok && a.Status != "" {
			return a.Status
		}
	}
	return "idle"
}

func (t *AgentsTab) workerMessage(name string) string {
	if t.workers == nil {
		return ""
	}
	for _, w := range t.workers {
		if w.Agent == name && w.Message != "Idle" && w.Message != "Completed" {
			return w.Message
		}
	}
	return ""
}

func statusIcon(status string) string {
	switch status {
	case "running":
		return runningStyle.Render("●")
	case "done":
		return doneStyle.Render("✓")
	case "error":
		return errStyle.Render("✗")
	case "queued":
		return queuedStyle.Render("⏳")
	default:
		return idleStyle.Render("○")
	}
}

func (t *AgentsTab) View() string {
	return t.Viewport.View()
}
