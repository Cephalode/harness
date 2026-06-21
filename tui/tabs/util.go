package tabs

import "strings"

// shortModel strips the provider prefix from a model name.
// "z-ai/glm-5.1" → "glm-5.1"
func shortModel(m string) string {
	if idx := strings.LastIndex(m, "/"); idx >= 0 {
		return m[idx+1:]
	}
	return m
}
