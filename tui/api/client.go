// Package api provides a client for the Harness Dashboard REST API + SSE event stream.
package api

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

// HarnessEvent represents a single event from the harness event stream.
type HarnessEvent struct {
	Type      string                 `json:"type"`
	Agent     string                 `json:"agent,omitempty"`
	Team      string                 `json:"team,omitempty"`
	Data      map[string]interface{} `json:"data,omitempty"`
	Timestamp float64                `json:"timestamp"`
}

// AgentState represents persisted agent state.
type AgentState struct {
	Name      string  `json:"name"`
	Status    string  `json:"status"`
	Model     string  `json:"model,omitempty"`
	Team      string  `json:"team,omitempty"`
	Task      string  `json:"task,omitempty"`
	Updated   float64 `json:"last_updated,omitempty"`
}

// TeamInfo represents the team tree structure.
type TeamInfo struct {
	Orchestrator struct {
		Name   string `json:"name"`
		Model  string `json:"model"`
		Status string `json:"status"`
	} `json:"orchestrator"`
	Teams []struct {
		Name    string `json:"name"`
		Color   string `json:"color"`
		Lead    Agent  `json:"lead"`
		Workers []Agent `json:"workers"`
	} `json:"teams"`
}

// Agent represents an agent in the team tree.
type Agent struct {
	Name   string `json:"name"`
	Model  string `json:"model"`
	Status string `json:"status"`
	Vision bool   `json:"vision,omitempty"`
}

// CostData represents cost breakdown.
type CostData struct {
	TotalCost  float64                `json:"total_cost"`
	TotalUsage struct {
		InputTokens  int64 `json:"input_tokens"`
		OutputTokens int64 `json:"output_tokens"`
	} `json:"total_usage"`
	ByAgent map[string]interface{} `json:"by_agent"`
	ByTeam  map[string]interface{} `json:"by_team"`
}

// SlotStatus represents slot allocation status.
type SlotStatus struct {
	Models map[string]ModelSlots `json:"models,omitempty"`
}

// ModelSlots represents per-model slot info.
type ModelSlots struct {
	Total      int      `json:"total"`
	Active     int      `json:"active"`
	Available  int      `json:"available"`
	Queued     int      `json:"queued"`
	AllocatedTo []string `json:"allocated_to,omitempty"`
}

// WorkerStatus represents a worker's latest status.
type WorkerStatus struct {
	Agent     string  `json:"agent"`
	Message   string  `json:"message"`
	Timestamp float64 `json:"timestamp"`
	Team      string  `json:"team,omitempty"`
	Task      string  `json:"task,omitempty"`
}

// QueueStatus represents the task queue state.
type QueueStatus struct {
	Length    int    `json:"length"`
	Current   string `json:"current,omitempty"`
	Positions []struct {
		TaskID  string `json:"task_id"`
		Message string `json:"message"`
	} `json:"positions,omitempty"`
}

// TaskResult represents a task's status/result.
type TaskResult struct {
	TaskID  string `json:"task_id,omitempty"`
	Status  string `json:"status,omitempty"`
	Result  string `json:"result,omitempty"`
	Error   string `json:"error,omitempty"`
}

// Client is the Harness Dashboard API client.
type Client struct {
	BaseURL    string
	HTTPClient *http.Client
}

// NewClient creates a new API client pointing at the dashboard server.
func NewClient(baseURL string) *Client {
	if strings.HasPrefix(baseURL, "http://") == false && strings.HasPrefix(baseURL, "https://") == false {
		baseURL = "http://" + baseURL
	}
	baseURL = strings.TrimRight(baseURL, "/")
	return &Client{
		BaseURL: baseURL,
		HTTPClient: &http.Client{Timeout: 10 * time.Second},
	}
}

// SendMessage enqueues a message and returns the task ID.
func (c *Client) SendMessage(ctx context.Context, message string) (*TaskResult, error) {
	body := fmt.Sprintf(`{"message": %q}`, message)
	req, err := http.NewRequestWithContext(ctx, "POST", c.BaseURL+"/api/message", strings.NewReader(body))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := c.HTTPClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != 200 {
		b, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("POST /api/message: %d: %s", resp.StatusCode, string(b))
	}

	var result TaskResult
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return nil, err
	}
	return &result, nil
}

// GetTeams fetches the team tree.
func (c *Client) GetTeams(ctx context.Context) (*TeamInfo, error) {
	req, err := http.NewRequestWithContext(ctx, "GET", c.BaseURL+"/api/teams", nil)
	if err != nil {
		return nil, err
	}
	resp, err := c.HTTPClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	var ti TeamInfo
	if err := json.NewDecoder(resp.Body).Decode(&ti); err != nil {
		return nil, err
	}
	return &ti, nil
}

// GetAgents fetches persisted agent states.
func (c *Client) GetAgents(ctx context.Context) (map[string]AgentState, error) {
	req, err := http.NewRequestWithContext(ctx, "GET", c.BaseURL+"/api/state/agents", nil)
	if err != nil {
		return nil, err
	}
	resp, err := c.HTTPClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	var wrapper struct {
		Agents map[string]AgentState `json:"agents"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&wrapper); err != nil {
		return nil, err
	}
	return wrapper.Agents, nil
}

// GetCosts fetches cost breakdown.
func (c *Client) GetCosts(ctx context.Context) (*CostData, error) {
	req, err := http.NewRequestWithContext(ctx, "GET", c.BaseURL+"/api/costs", nil)
	if err != nil {
		return nil, err
	}
	resp, err := c.HTTPClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	var cd CostData
	if err := json.NewDecoder(resp.Body).Decode(&cd); err != nil {
		return nil, err
	}
	return &cd, nil
}

// GetSlots fetches slot allocation status.
func (c *Client) GetSlots(ctx context.Context) (*SlotStatus, error) {
	req, err := http.NewRequestWithContext(ctx, "GET", c.BaseURL+"/api/slots", nil)
	if err != nil {
		return nil, err
	}
	resp, err := c.HTTPClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	var ss SlotStatus
	if err := json.NewDecoder(resp.Body).Decode(&ss); err != nil {
		return nil, err
	}
	return &ss, nil
}

// GetWorkerStatuses fetches worker status messages.
func (c *Client) GetWorkerStatuses(ctx context.Context) ([]WorkerStatus, error) {
	req, err := http.NewRequestWithContext(ctx, "GET", c.BaseURL+"/api/worker-statuses", nil)
	if err != nil {
		return nil, err
	}
	resp, err := c.HTTPClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	var wrapper struct {
		Workers []WorkerStatus `json:"workers"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&wrapper); err != nil {
		return nil, err
	}
	return wrapper.Workers, nil
}

// GetQueue fetches the task queue status.
func (c *Client) GetQueue(ctx context.Context) (*QueueStatus, error) {
	req, err := http.NewRequestWithContext(ctx, "GET", c.BaseURL+"/api/queue", nil)
	if err != nil {
		return nil, err
	}
	resp, err := c.HTTPClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	var qs QueueStatus
	if err := json.NewDecoder(resp.Body).Decode(&qs); err != nil {
		return nil, err
	}
	return &qs, nil
}

// GetTask fetches a specific task result.
func (c *Client) GetTask(ctx context.Context, taskID string) (*TaskResult, error) {
	req, err := http.NewRequestWithContext(ctx, "GET", c.BaseURL+"/api/task/"+taskID, nil)
	if err != nil {
		return nil, err
	}
	resp, err := c.HTTPClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	var tr TaskResult
	if err := json.NewDecoder(resp.Body).Decode(&tr); err != nil {
		return nil, err
	}
	return &tr, nil
}

// StreamEvents connects to the SSE endpoint and sends events to the channel.
// Blocks until context is cancelled or connection lost.
func (c *Client) StreamEvents(ctx context.Context, ch chan<- HarnessEvent) error {
	// Use a longer timeout client for SSE
	sseClient := &http.Client{Timeout: 0}
	req, err := http.NewRequestWithContext(ctx, "GET", c.BaseURL+"/api/state/events/stream", nil)
	if err != nil {
		return err
	}
	req.Header.Set("Accept", "text/event-stream")

	resp, err := sseClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	if resp.StatusCode != 200 {
		b, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("SSE: %d: %s", resp.StatusCode, string(b))
	}

	scanner := bufio.NewScanner(resp.Body)
	scanner.Buffer(make([]byte, 0, 64*1024), 1024*1024)

	for scanner.Scan() {
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
		}

		line := scanner.Text()
		if !strings.HasPrefix(line, "data: ") {
			continue
		}
		data := strings.TrimPrefix(line, "data: ")

		var event HarnessEvent
		if err := json.Unmarshal([]byte(data), &event); err != nil {
			// Skip non-event lines (heartbeats, init snapshots)
			continue
		}

		// Skip heartbeats and init events
		if event.Type == "heartbeat" || event.Type == "init" {
			continue
		}

		select {
		case ch <- event:
		case <-ctx.Done():
			return ctx.Err()
		}
	}

	return scanner.Err()
}
