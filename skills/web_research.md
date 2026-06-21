# Web Research Tools

You have access to web search, page reader, and research synthesis via Z.AI's APIs.

## Commands

All commands must run from workdir `~/devel/harness/`. All output is **JSON**.

```bash
# Web search — find URLs and snippets for a query
python -m harness.web_tools search "your query"

# Page reader — fetch a URL and convert to markdown
python -m harness.web_tools reader "https://example.com"

# End-to-end research — search + read + synthesize in one call
python -m harness.web_tools zread "your research question"
```

## When to Use Each

| Tool | Use When |
|------|---------|
| `search` | You need URLs, titles, and snippets. Good for finding sources. |
| `reader` | You have a specific URL and need its full content as markdown. |
| `zread` | You want a synthesized answer with sources. Best for complex questions. |

## Using Results

1. Always check `"ok": true` before using any result. If `false`, check the `"error"` field.
2. Parse JSON output with `jq` in bash or `json.loads()` in Python.
3. Search results: look at `results[].title`, `results[].link`, `results[].content`.
4. Reader results: use `content` (markdown), `title`, and `url`.
5. Zread results: use `answer` (synthesized text) and `sources[]` (referenced URLs).

## Research Workflow

For multi-step research:
1. `search` — find relevant URLs
2. `reader` — read the most promising pages
3. Synthesize findings into your report with citations
