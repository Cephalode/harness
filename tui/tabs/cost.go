package tabs

import (
	"fmt"
	"sort"
	"strings"

	"github.com/cephalode/harness-tui/api"

	"github.com/charmbracelet/bubbles/viewport"
)

var (
	costHeaderStyle = headerStyle
	costDimStyle    = dimStyle
	costValStyle    = doneStyle
)

// CostTab shows cost and token usage breakdown.
type CostTab struct {
	Viewport viewport.Model
	costs    *api.CostData
	width    int
	height   int
}

func NewCostTab() *CostTab {
	vp := viewport.New(80, 20)
	return &CostTab{Viewport: vp}
}

func (t *CostTab) SetSize(width, height int) {
	t.width = width
	t.height = height
	t.Viewport.Width = width
	t.Viewport.Height = height
}

func (t *CostTab) SetCosts(costs *api.CostData) {
	t.costs = costs
	t.render()
}

func (t *CostTab) render() {
	var b strings.Builder

	fmt.Fprintf(&b, "%s\n\n", costHeaderStyle.Render("Cost Breakdown"))

	if t.costs == nil {
		b.WriteString(costDimStyle.Render("No cost data..."))
		t.Viewport.SetContent(b.String())
		return
	}

	// Summary
	fmt.Fprintf(&b, "Total Cost:  %s\n", costValStyle.Render(fmt.Sprintf("$%.4f", t.costs.TotalCost)))
	fmt.Fprintf(&b, "Input:       %s tokens\n", formatInt(t.costs.TotalUsage.InputTokens))
	fmt.Fprintf(&b, "Output:      %s tokens\n", formatInt(t.costs.TotalUsage.OutputTokens))

	// By agent
	if t.costs.ByAgent != nil && len(t.costs.ByAgent) > 0 {
		b.WriteString("\n")
		fmt.Fprintf(&b, "%s\n", costHeaderStyle.Render("By Agent"))

		// Sort agent names
		agents := make([]string, 0, len(t.costs.ByAgent))
		for name := range t.costs.ByAgent {
			agents = append(agents, name)
		}
		sort.Strings(agents)

		for _, name := range agents {
			data := t.costs.ByAgent[name]
			b.WriteString(t.renderCostEntry("  ", name, data))
		}
	}

	// By team
	if t.costs.ByTeam != nil && len(t.costs.ByTeam) > 0 {
		b.WriteString("\n")
		fmt.Fprintf(&b, "%s\n", costHeaderStyle.Render("By Team"))

		teams := make([]string, 0, len(t.costs.ByTeam))
		for name := range t.costs.ByTeam {
			teams = append(teams, name)
		}
		sort.Strings(teams)

		for _, name := range teams {
			data := t.costs.ByTeam[name]
			b.WriteString(t.renderCostEntry("  ", name, data))
		}
	}

	t.Viewport.SetContent(b.String())
}

func (t *CostTab) renderCostEntry(prefix, name string, data interface{}) string {
	// Data is a map[string]interface{} from the API
	m, ok := data.(map[string]interface{})
	if !ok {
		return fmt.Sprintf("%s%-25s (unknown format)\n", prefix, name)
	}

	input := formatFloat(m["input_tokens"])
	output := formatFloat(m["output_tokens"])
	cost := ""
	if c, ok := m["cost"].(float64); ok {
		cost = fmt.Sprintf("$%.4f", c)
	}

	return fmt.Sprintf("%s%-25s in:%s out:%s %s\n",
		prefix,
		name,
		input,
		output,
		costValStyle.Render(cost),
	)
}

func formatInt(n int64) string {
	s := fmt.Sprintf("%d", n)
	if len(s) <= 3 {
		return s
	}
	result := ""
	for i, c := range s {
		if i > 0 && (len(s)-i)%3 == 0 {
			result += ","
		}
		result += string(c)
	}
	return result
}

func formatFloat(v interface{}) string {
	if v == nil {
		return "0"
	}
	if f, ok := v.(float64); ok {
		return formatInt(int64(f))
	}
	return fmt.Sprintf("%v", v)
}

func (t *CostTab) View() string {
	return t.Viewport.View()
}
