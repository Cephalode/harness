package main

import (
	"context"
	"fmt"
	"os"
	"time"

	"github.com/cephalode/harness-tui/api"
	"github.com/cephalode/harness-tui/tabs"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/bubbles/textinput"
	"github.com/charmbracelet/lipgloss"
)

// Tab indices
const (
	TabActivity = iota
	TabAgents
	TabSlots
	TabCost
	TabCount
)

var tabNames = []string{"Activity", "Agents", "Slots", "Cost"}

// Styles
var (
	titleStyle = lipgloss.NewStyle().
			Bold(true).
			Foreground(lipgloss.Color("#FAFAFA")).
			Background(lipgloss.Color("#7D56F4")).
			Padding(0, 2)

	activeTabStyle = lipgloss.NewStyle().
			Bold(true).
			Foreground(lipgloss.Color("#FFFFFF")).
			Background(lipgloss.Color("#7D56F4")).
			Padding(0, 2).
			MarginRight(1)

	inactiveTabStyle = lipgloss.NewStyle().
				Foreground(lipgloss.Color("#888888")).
				Background(lipgloss.Color("#333333")).
				Padding(0, 2).
				MarginRight(1)

	statusBarStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color("#FAFAFA")).
			Background(lipgloss.Color("#333333")).
			Padding(0, 2)

	inputPromptStyle = lipgloss.NewStyle().
				Foreground(lipgloss.Color("#7D56F4")).
				Bold(true)

	errorStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color("#FF5555"))

	connectedStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color("#50FA7B"))

	disconnectedStyle = lipgloss.NewStyle().
				Foreground(lipgloss.Color("#FF5555"))
)

// Messages (Bubble Tea Msg types)

type eventMsg struct{ event api.HarnessEvent }
type tickMsg struct{ time time.Time }
type agentsFetchedMsg struct {
	agents map[string]api.AgentState
	err    error
}
type teamsFetchedMsg struct {
	teams *api.TeamInfo
	err   error
}
type costsFetchedMsg struct {
	costs *api.CostData
	err   error
}
type slotsFetchedMsg struct {
	slots *api.SlotStatus
	err   error
}
type workerStatusesMsg struct {
	workers []api.WorkerStatus
	err     error
}
type messageSentMsg struct {
	result *api.TaskResult
	err    error
}
type connectionStatusMsg struct{ connected bool }

// Model is the top-level Bubble Tea model.
type Model struct {
	client      *api.Client
	ctx         context.Context
	cancel      context.CancelFunc
	eventCh     chan api.HarnessEvent

	activeTab   int
	width       int
	height      int

	// Sub-models
	activity    *tabs.ActivityTab
	agentsTab   *tabs.AgentsTab
	slotsTab    *tabs.SlotsTab
	costTab     *tabs.CostTab

	// Input
	input       textinput.Model
	inputMode   bool // true when user is typing

	// State
	connected   bool
	lastError   string
	lastTick    time.Time
	taskQueue   *api.QueueStatus
}

func NewModel(serverURL string) Model {
	ctx, cancel := context.WithCancel(context.Background())
	client := api.NewClient(serverURL)
	eventCh := make(chan api.HarnessEvent, 256)

	// Input
	ti := textinput.New()
	ti.Prompt = "▸ "
	ti.Placeholder = "Type a message to send to the harness..."
	ti.CharLimit = 2000
	ti.Width = 60

	return Model{
		client:    client,
		ctx:       ctx,
		cancel:    cancel,
		eventCh:   eventCh,
		activity:  tabs.NewActivityTab(),
		agentsTab: tabs.NewAgentsTab(),
		slotsTab:  tabs.NewSlotsTab(),
		costTab:   tabs.NewCostTab(),
		input:     ti,
	}
}

// Init starts the program.
func (m Model) Init() tea.Cmd {
	return tea.Batch(
		m.waitForEvent(),  // start listening on eventCh (fed by main goroutine)
		m.pollAgents(),
		m.pollTeams(),
		m.pollCosts(),
		m.pollSlots(),
		m.pollWorkerStatuses(),
		m.tickEvery(),
		m.checkConnection(),
	)
}

func (m Model) waitForEvent() tea.Cmd {
	return func() tea.Msg {
		select {
		case e, ok := <-m.eventCh:
			if !ok {
				return nil
			}
			return eventMsg{event: e}
		case <-m.ctx.Done():
			return nil
		}
	}
}

func (m Model) tickEvery() tea.Cmd {
	return tea.Tick(2*time.Second, func(t time.Time) tea.Msg {
		return tickMsg{time: t}
	})
}

func (m Model) pollAgents() tea.Cmd {
	return func() tea.Msg {
		agents, err := m.client.GetAgents(m.ctx)
		return agentsFetchedMsg{agents: agents, err: err}
	}
}

func (m Model) pollTeams() tea.Cmd {
	return func() tea.Msg {
		teams, err := m.client.GetTeams(m.ctx)
		return teamsFetchedMsg{teams: teams, err: err}
	}
}

func (m Model) pollCosts() tea.Cmd {
	return func() tea.Msg {
		costs, err := m.client.GetCosts(m.ctx)
		return costsFetchedMsg{costs: costs, err: err}
	}
}

func (m Model) pollSlots() tea.Cmd {
	return func() tea.Msg {
		slots, err := m.client.GetSlots(m.ctx)
		return slotsFetchedMsg{slots: slots, err: err}
	}
}

func (m Model) pollWorkerStatuses() tea.Cmd {
	return func() tea.Msg {
		workers, err := m.client.GetWorkerStatuses(m.ctx)
		return workerStatusesMsg{workers: workers, err: err}
	}
}

func (m Model) sendMessage(msg string) tea.Cmd {
	return func() tea.Msg {
		result, err := m.client.SendMessage(m.ctx, msg)
		return messageSentMsg{result: result, err: err}
	}
}

func (m Model) checkConnection() tea.Cmd {
	return func() tea.Msg {
		ctx, cancel := context.WithTimeout(m.ctx, 3*time.Second)
		defer cancel()
		_, err := m.client.GetQueue(ctx)
		return connectionStatusMsg{connected: err == nil}
	}
}

// Update handles messages.
func (m Model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	var cmds []tea.Cmd

	switch msg := msg.(type) {
	case tea.WindowSizeMsg:
		m.width = msg.Width
		m.height = msg.Height
		// Resize sub-components
		mainHeight := m.height - 5 // tabs + status + input
		if mainHeight < 5 {
			mainHeight = 5
		}
		m.activity.SetSize(m.width, mainHeight)
		m.agentsTab.SetSize(m.width, mainHeight)
		m.slotsTab.SetSize(m.width, mainHeight)
		m.costTab.SetSize(m.width, mainHeight)

	case tea.KeyMsg:
		switch msg.String() {
		case "ctrl+c", "q":
			if !m.inputMode {
				m.cancel()
				return m, tea.Quit
			}
		case "enter":
			if m.inputMode {
				val := m.input.Value()
				if val != "" {
					cmds = append(cmds, m.sendMessage(val))
					m.input.SetValue("")
				}
				m.inputMode = false
				m.input.Blur()
			} else {
				// Start input mode
				m.inputMode = true
				cmds = append(cmds, m.input.Focus())
			}
		case "esc":
			if m.inputMode {
				m.inputMode = false
				m.input.Blur()
			}
		case "1":
			if !m.inputMode {
				m.activeTab = TabActivity
			}
		case "2":
			if !m.inputMode {
				m.activeTab = TabAgents
			}
		case "3":
			if !m.inputMode {
				m.activeTab = TabSlots
			}
		case "4":
			if !m.inputMode {
				m.activeTab = TabCost
			}
		case "tab":
			if !m.inputMode {
				m.activeTab = (m.activeTab + 1) % TabCount
			}
		}

	case eventMsg:
		m.activity.AddEvent(msg.event)
		m.agentsTab.UpdateFromEvent(msg.event)
		cmds = append(cmds, m.waitForEvent())

	case tickMsg:
		m.lastTick = msg.time
		cmds = append(cmds,
			m.pollAgents(),
			m.pollCosts(),
			m.pollSlots(),
			m.pollWorkerStatuses(),
			m.tickEvery(),
			m.checkConnection(),
		)

	case agentsFetchedMsg:
		if msg.err == nil {
			m.agentsTab.SetAgents(msg.agents)
		}

	case teamsFetchedMsg:
		if msg.err == nil && msg.teams != nil {
			m.agentsTab.SetTeams(msg.teams)
		}

	case costsFetchedMsg:
		if msg.err == nil && msg.costs != nil {
			m.costTab.SetCosts(msg.costs)
		}

	case slotsFetchedMsg:
		if msg.err == nil && msg.slots != nil {
			m.slotsTab.SetSlots(msg.slots)
		}

	case workerStatusesMsg:
		if msg.err == nil {
			m.agentsTab.SetWorkerStatuses(msg.workers)
		}

	case messageSentMsg:
		if msg.err != nil {
			m.lastError = fmt.Sprintf("send failed: %v", msg.err)
		} else if msg.result != nil {
			m.activity.AddSystemEvent(fmt.Sprintf("Task queued: %s", msg.result.TaskID))
		}

	case connectionStatusMsg:
		m.connected = msg.connected
		if msg.connected {
			// Restart SSE if reconnected
			cmds = append(cmds, m.waitForEvent())
		}
	}

	// Update input
	if m.inputMode {
		var icmd tea.Cmd
		m.input, icmd = m.input.Update(msg)
		cmds = append(cmds, icmd)
	}

	// Update active viewport
	switch m.activeTab {
	case TabActivity:
		cmds = append(cmds, m.activity.UpdateAsViewport(msg))
	case TabAgents:
		// Agents tab uses its own viewport
		var vcmd tea.Cmd
		m.agentsTab.Viewport, vcmd = m.agentsTab.Viewport.Update(msg)
		cmds = append(cmds, vcmd)
	case TabSlots:
		var vcmd tea.Cmd
		m.slotsTab.Viewport, vcmd = m.slotsTab.Viewport.Update(msg)
		cmds = append(cmds, vcmd)
	case TabCost:
		var vcmd tea.Cmd
		m.costTab.Viewport, vcmd = m.costTab.Viewport.Update(msg)
		cmds = append(cmds, vcmd)
	}

	return m, tea.Batch(cmds...)
}

// View renders the UI.
func (m Model) View() string {
	if m.width == 0 {
		return "Loading..."
	}

	// Render tabs
	var tabsStr string
	for i, name := range tabNames {
		if i == m.activeTab {
			tabsStr += activeTabStyle.Render(name)
		} else {
			tabsStr += inactiveTabStyle.Render(name)
		}
	}

	// Render active tab content
	var content string
	switch m.activeTab {
	case TabActivity:
		content = m.activity.View()
	case TabAgents:
		content = m.agentsTab.View()
	case TabSlots:
		content = m.slotsTab.View()
	case TabCost:
		content = m.costTab.View()
	}

	// Status bar
	connStr := "● disconnected"
	if m.connected {
		connStr = connectedStyle.Render("● connected")
	} else {
		connStr = disconnectedStyle.Render("● disconnected")
	}

	queueStr := ""
	if m.taskQueue != nil && m.taskQueue.Length > 0 {
		queueStr = fmt.Sprintf(" │ queue: %d", m.taskQueue.Length)
	}

	statusBar := statusBarStyle.Render(
		fmt.Sprintf("%s │ %s%s │ press Enter to send, 1-4 tabs, q quit",
			connStr,
			time.Now().Format("15:04:05"),
			queueStr,
		),
	)

	// Input bar
	var inputBar string
	if m.inputMode {
		inputBar = inputPromptStyle.Render("⏎ ") + m.input.View()
	} else {
		inputBar = lipgloss.NewStyle().Foreground(lipgloss.Color("#666666")).Render("  Press Enter to type a message...")
	}

	// Error
	if m.lastError != "" {
		statusBar += "\n" + errorStyle.Render(m.lastError)
		m.lastError = ""
	}

	// Compose
	return fmt.Sprintf("%s\n%s\n%s\n%s", tabsStr, content, statusBar, inputBar)
}

func main() {
	serverURL := "http://localhost:5174"
	if len(os.Args) > 1 {
		serverURL = os.Args[1]
	}

	model := NewModel(serverURL)

	// Start SSE listener in background — it feeds events into eventCh
	go func() {
		// Retry loop
		for {
			err := model.client.StreamEvents(model.ctx, model.eventCh)
			if model.ctx.Err() != nil {
				return
			}
			if err != nil {
				// Wait and retry
				select {
				case <-time.After(3 * time.Second):
				case <-model.ctx.Done():
					return
				}
			}
		}
	}()

	p := tea.NewProgram(model, tea.WithAltScreen())
	if _, err := p.Run(); err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(1)
	}
}
