package tabs

import (
	"fmt"
	"strings"
	"time"

	"github.com/cephalode/harness-tui/api"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/bubbles/viewport"
	"github.com/charmbracelet/lipgloss"
)

var (
	eventStyle = lipgloss.NewStyle().Foreground(lipgloss.Color("#888888"))
	timeStyle  = lipgloss.NewStyle().Foreground(lipgloss.Color("#666666"))

	agentStyle   = lipgloss.NewStyle().Foreground(lipgloss.Color("#7D56F4")).Bold(true)
	teamStyle    = lipgloss.NewStyle().Foreground(lipgloss.Color("#50FA7B"))
	systemStyle  = lipgloss.NewStyle().Foreground(lipgloss.Color("#FFB86C"))

	startStyle   = lipgloss.NewStyle().Foreground(lipgloss.Color("#50FA7B"))
	endStyle     = lipgloss.NewStyle().Foreground(lipgloss.Color("#8BE9FD"))
	errorStyle   = lipgloss.NewStyle().Foreground(lipgloss.Color("#FF5555"))
	queueStyle   = lipgloss.NewStyle().Foreground(lipgloss.Color("#FFB86C"))
	routingStyle = lipgloss.NewStyle().Foreground(lipgloss.Color("#BD93F9"))
	degradeStyle = lipgloss.NewStyle().Foreground(lipgloss.Color("#FF79C6"))
	workerStyle  = lipgloss.NewStyle().Foreground(lipgloss.Color("#F1FA8C"))
	responseStyle = lipgloss.NewStyle().Foreground(lipgloss.Color("#BD93F9")).Italic(true)
)

const maxEvents = 500

// ActivityTab shows a live scrolling feed of harness events.
type ActivityTab struct {
	Viewport viewport.Model
	events   []string
	ready    bool
	width    int
	height   int
}

func NewActivityTab() *ActivityTab {
	vp := viewport.New(80, 20)
	return &ActivityTab{
		Viewport: vp,
		events:   make([]string, 0, maxEvents),
		ready:    true,
	}
}

func (t *ActivityTab) SetSize(width, height int) {
	t.width = width
	t.height = height
	t.Viewport.Width = width
	t.Viewport.Height = height
}

func (t *ActivityTab) AddEvent(e api.HarnessEvent) {
	line := formatEvent(e)
	t.events = append(t.events, line)
	if len(t.events) > maxEvents {
		t.events = t.events[len(t.events)-maxEvents:]
	}
	t.refresh()
}

func (t *ActivityTab) AddSystemEvent(msg string) {
	line := systemStyle.Render(fmt.Sprintf("[system] %s", msg))
	t.events = append(t.events, line)
	if len(t.events) > maxEvents {
		t.events = t.events[len(t.events)-maxEvents:]
	}
	t.refresh()
}

func (t *ActivityTab) refresh() {
	content := strings.Join(t.events, "\n")
	t.Viewport.SetContent(content)
	t.Viewport.GotoBottom()
}

func (t *ActivityTab) UpdateAsViewport(msg interface{}) tea.Cmd {
	var cmd tea.Cmd
	t.Viewport, cmd = t.Viewport.Update(msg)
	return cmd
}

func (t *ActivityTab) View() string {
	if len(t.events) == 0 {
		return lipgloss.NewStyle().Foreground(lipgloss.Color("#666666")).Render(
			"Waiting for events...",
		)
	}
	return t.Viewport.View()
}

func formatEvent(e api.HarnessEvent) string {
	ts := ""
	if e.Timestamp > 0 {
		ts = time.Unix(int64(e.Timestamp), 0).Format("15:04:05")
	}

	tsPart := timeStyle.Render(ts)

	var parts []string
	parts = append(parts, tsPart)

	switch e.Type {
	case "agent_start":
		agent := e.Agent
		if agent == "" {
			agent = "unknown"
		}
		model := ""
		if m, ok := e.Data["model"].(string); ok {
			model = fmt.Sprintf(" (%s)", shortModel(m))
		}
		parts = append(parts, startStyle.Render("▶ "+agent+model))

	case "agent_end":
		agent := e.Agent
		if agent == "" {
			agent = "unknown"
		}
		status := ""
		if s, ok := e.Data["status"].(string); ok {
			if s == "error" {
				status = errorStyle.Render(" ✗")
			} else {
				status = endStyle.Render(" ✓")
			}
		}
		dur := ""
		if d, ok := e.Data["duration_ms"].(float64); ok {
			dur = fmt.Sprintf(" %.1fs", d/1000)
		}
		parts = append(parts, endStyle.Render("■ "+agent)+status+dur)

	case "agent_error":
		agent := e.Agent
		errMsg := ""
		if em, ok := e.Data["error"].(string); ok {
			errMsg = ": " + em
		}
		parts = append(parts, errorStyle.Render(fmt.Sprintf("✗ %s%s", agent, errMsg)))

	case "team_start":
		parts = append(parts, startStyle.Render(fmt.Sprintf("┌ team %s started", e.Team)))

	case "team_done":
		rounds := ""
		if r, ok := e.Data["rounds"].(float64); ok {
			rounds = fmt.Sprintf(" (%d rounds)", int(r))
		}
		workers := ""
		if w, ok := e.Data["workers_used"].(float64); ok {
			workers = fmt.Sprintf(" %d workers", int(w))
		}
		parts = append(parts, endStyle.Render(fmt.Sprintf("└ team %s done%s%s", e.Team, rounds, workers)))

	case "routing":
		teams := ""
		if tl, ok := e.Data["teams"].([]interface{}); ok {
			names := make([]string, len(tl))
			for i, t := range tl {
				names[i] = fmt.Sprintf("%v", t)
			}
			teams = strings.Join(names, ", ")
		}
		parts = append(parts, routingStyle.Render(fmt.Sprintf("→ routing → %s", teams)))

	case "session_start", "session_end":
		parts = append(parts, eventStyle.Render(fmt.Sprintf("  %s", e.Type)))

	case "model_degradation":
		orig := ""
		alloc := ""
		if o, ok := e.Data["original_model"].(string); ok {
			orig = shortModel(o)
		}
		if a, ok := e.Data["allocated_model"].(string); ok {
			alloc = shortModel(a)
		}
		parts = append(parts, degradeStyle.Render(fmt.Sprintf("↓ %s: %s → %s", e.Agent, orig, alloc)))

	case "model_queued":
		model := ""
		wait := ""
		if m, ok := e.Data["model"].(string); ok {
			model = shortModel(m)
		}
		if w, ok := e.Data["wait_seconds"].(float64); ok {
			wait = fmt.Sprintf(" %.0fs", w)
		}
		parts = append(parts, queueStyle.Render(fmt.Sprintf("⏳ %s queued on %s%s", e.Agent, model, wait)))

	case "worker_status":
		agent := e.Agent
		message := ""
		if m, ok := e.Data["message"].(string); ok {
			message = m
		}
		parts = append(parts, workerStyle.Render(fmt.Sprintf("  %s: %s", agent, message)))

	case "task_queued":
		parts = append(parts, systemStyle.Render("📋 task queued"))

	case "task_started":
		parts = append(parts, startStyle.Render("▶ task started"))

	case "task_completed":
		parts = append(parts, endStyle.Render("✓ task completed"))
		if resp, ok := e.Data["result"].(string); ok && resp != "" {
			preview := resp
			if len(preview) > 500 {
				preview = preview[:500] + "..."
			}
			parts = append(parts, responseStyle.Render(preview))
		}

	case "task_failed":
		errMsg := ""
		if em, ok := e.Data["error"].(string); ok {
			errMsg = ": " + em
		}
		parts = append(parts, errorStyle.Render(fmt.Sprintf("✗ task failed%s", errMsg)))

	default:
		parts = append(parts, eventStyle.Render(fmt.Sprintf("  %s %v", e.Type, e.Agent)))
	}

	return strings.Join(parts, " ")
}


