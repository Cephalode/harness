package tabs

import (
	"fmt"
	"sort"
	"strings"

	"github.com/cephalode/harness-tui/api"

	"github.com/charmbracelet/bubbles/viewport"
)

// SlotsTab shows per-model concurrency/slot status.
type SlotsTab struct {
	Viewport viewport.Model
	slots    *api.SlotStatus
	width    int
	height   int
}

func NewSlotsTab() *SlotsTab {
	vp := viewport.New(80, 20)
	return &SlotsTab{Viewport: vp}
}

func (t *SlotsTab) SetSize(width, height int) {
	t.width = width
	t.height = height
	t.Viewport.Width = width
	t.Viewport.Height = height
}

func (t *SlotsTab) SetSlots(slots *api.SlotStatus) {
	t.slots = slots
	t.render()
}

func (t *SlotsTab) render() {
	var b strings.Builder

	fmt.Fprintf(&b, "%s\n\n", headerStyle.Render("Model Slots"))

	if t.slots == nil || len(t.slots.Models) == 0 {
		b.WriteString(dimStyle.Render("No slot data..."))
		t.Viewport.SetContent(b.String())
		return
	}

	// Header row
	fmt.Fprintf(&b, "%s%-20s %6s %6s %6s %6s  %s\n",
		headerStyle.Render(""),
		"Model", "Total", "Active", "Free", "Queue", "Allocated To",
	)

	// Sort models
	names := make([]string, 0, len(t.slots.Models))
	for n := range t.slots.Models {
		names = append(names, n)
	}
	sort.Strings(names)

	for _, name := range names {
		m := t.slots.Models[name]
		shortName := shortModel(name)

		bar := renderBar(m.Active, m.Total, 20)

		var allocStr string
		if len(m.AllocatedTo) > 0 {
			allocStr = strings.Join(m.AllocatedTo, ", ")
		} else {
			allocStr = dimStyle.Render("—")
		}

		fmt.Fprintf(&b, "%-20s %6d %s %6d %6d  %s\n",
			shortName,
			m.Total,
			bar,
			m.Available,
			m.Queued,
			allocStr,
		)
	}

	// Summary
	totalActive := 0
	totalSlots := 0
	for _, m := range t.slots.Models {
		totalActive += m.Active
		totalSlots += m.Total
	}
	b.WriteString("\n")
	fmt.Fprintf(&b, "Total: %d/%d slots in use\n", totalActive, totalSlots)

	t.Viewport.SetContent(b.String())
}

func renderBar(active, total, width int) string {
	if total == 0 {
		return dimStyle.Render(strings.Repeat("·", width))
	}
	filled := int(float64(width) * float64(active) / float64(total))
	if filled > width {
		filled = width
	}
	empty := width - filled

	bar := runningStyle.Render(strings.Repeat("█", filled)) +
		dimStyle.Render(strings.Repeat("░", empty))
	return bar
}

func (t *SlotsTab) View() string {
	return t.Viewport.View()
}
