"""Z.AI Web Search, Reader, and Zread API wrappers for the harness agent system.

Provides three web capabilities:
  - web_search: Search the web (standalone API with chat-based fallback)
  - web_reader: Fetch and convert web pages to markdown
  - zread: Agent-style search+synthesis via chat completions with web_search tool

Usage from CLI (JSON output for agent parsing):
    python -m harness.web_tools search "query"
    python -m harness.web_tools reader "https://example.com"
    python -m harness.web_tools zread "query"
"""

from __future__ import annotations

import re
import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_URL = "https://api.z.ai/api/coding/paas/v4"
DEFAULT_MODEL = "glm-4.5-air"
DEFAULT_TIMEOUT = 30
READER_TIMEOUT = 45

# ---------------------------------------------------------------------------
# API key resolution
# ---------------------------------------------------------------------------


def _load_env_file(path: Path) -> dict[str, str]:
    """Parse a simple .env file (KEY=VALUE lines, no quoting logic needed)."""
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip()
    return env


def resolve_api_key(explicit: str | None = None) -> str:
    """Return a Z.AI API key, checking several sources in order.

    Priority: explicit param → GLM_API_KEY env var → ~/.hermes/.env file.
    """
    if explicit:
        return explicit

    env_val = os.environ.get("GLM_API_KEY")
    if env_val:
        return env_val

    # Try ~/.hermes/.env
    hermes_env = Path.home() / ".hermes" / ".env"
    if hermes_env.exists():
        env_map = _load_env_file(hermes_env)
        if "GLM_API_KEY" in env_map:
            return env_map["GLM_API_KEY"]

    raise RuntimeError(
        "No Z.AI API key found. Set GLM_API_KEY env var, "
        "add it to ~/.hermes/.env, or pass api_key= to WebTools()."
    )


# ---------------------------------------------------------------------------
# WebTools class
# ---------------------------------------------------------------------------


class WebTools:
    """Wraps Z.AI's Web Search, Reader, and Zread APIs.

    Parameters
    ----------
    api_key:
        Bearer token for Z.AI. If *None*, resolved automatically via
        :func:`resolve_api_key`.
    timeout:
        Default request timeout in seconds (applies to search and chat calls).
    """

    def __init__(self, api_key: str | None = None, timeout: int = DEFAULT_TIMEOUT) -> None:
        self.api_key = resolve_api_key(api_key)
        self.timeout = timeout
        self._headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "HarnessWebTools/1.0 (compatible; research-agent)",
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _post(self, endpoint: str, payload: dict[str, Any], timeout: int | None = None) -> dict[str, Any]:
        """POST to Z.AI and return parsed JSON. Raises on HTTP errors."""
        url = f"{BASE_URL}/{endpoint.lstrip('/')}"
        body = json.dumps(payload).encode("utf-8")
        req = Request(url, data=body, headers=self._headers, method="POST")
        effective_timeout = timeout or self.timeout
        with urlopen(req, timeout=effective_timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw)

    @staticmethod
    def _error_result(method: str, message: str, **extra: Any) -> dict[str, Any]:
        return {
            "ok": False,
            "method": method,
            "error": message,
            "timestamp": time.time(),
            **extra,
        }

    # ------------------------------------------------------------------
    # 1. Web Reader
    # ------------------------------------------------------------------

    def web_reader(self, url: str, format: str = "markdown") -> dict[str, Any]:
        """Fetch a web page and return its content converted to the requested format.

        Returns
        -------
        dict with keys: ok, method, url, title, content, metadata (on success)
                       ok=False, error (on failure)
        """
        # Basic URL validation
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return self._error_result("web_reader", f"Invalid URL scheme: {parsed.scheme}", url=url)

        payload: dict[str, Any] = {
            "url": url,
            "return_format": format,
            "retain_images": False,
            "timeout": READER_TIMEOUT,
        }

        try:
            data = self._post("reader", payload, timeout=READER_TIMEOUT + 10)
        except TimeoutError:
            return self._error_result("web_reader", f"Request timed out after {READER_TIMEOUT + 10}s", url=url)
        except (URLError, OSError) as exc:
            return self._error_result("web_reader", str(exc), url=url)

        reader_result = data.get("reader_result", {})
        if not reader_result:
            return self._error_result("web_reader", "Empty reader_result from API", url=url, raw=data)

        return {
            "ok": True,
            "method": "web_reader",
            "url": reader_result.get("url", url),
            "title": reader_result.get("title", ""),
            "content": reader_result.get("content", ""),
            "metadata": reader_result.get("metadata", {}),
            "timestamp": time.time(),
        }

    # ------------------------------------------------------------------
    # 2. Web Search (standalone + chat-based fallback)
    # ------------------------------------------------------------------

    def web_search(self, query: str, engine: str = "search_std", count: int = 10) -> dict[str, Any]:
        """Search the web. Tries the standalone API first; falls back to chat-based search.

        Parameters
        ----------
        query:
            Search query string.
        engine:
            Search engine identifier (default ``"search_std"``).
        count:
            Maximum number of results to request.

        Returns
        -------
        dict with keys: ok, method, query, results (list), source ("standalone" or "chat_fallback")
        """
        # --- Try standalone first ---
        standalone = self._standalone_search(query, engine, count)
        if standalone["ok"]:
            return standalone

        # --- Fallback to chat-based search ---
        return self._chat_search(query)

    def _standalone_search(self, query: str, engine: str, count: int) -> dict[str, Any]:
        """Standalone /web_search endpoint."""
        payload = {
            "search_engine": engine,
            "search_query": query,
            "search_intent": False,
            "count": count,
        }
        try:
            data = self._post("web_search", payload)
        except (URLError, OSError) as exc:
            return self._error_result("web_search", f"Standalone search failed: {exc}", query=query)

        search_results = data.get("search_result", [])
        if not isinstance(search_results, list):
            return self._error_result("web_search", "Unexpected search_result format", query=query, raw=data)

        return {
            "ok": True,
            "method": "web_search",
            "query": query,
            "results": [
                {
                    "title": r.get("title", ""),
                    "link": r.get("link", ""),
                    "content": r.get("content", ""),
                    "media": r.get("media", ""),
                }
                for r in search_results
            ],
            "source": "standalone",
            "timestamp": time.time(),
        }

    def _chat_search(self, query: str) -> dict[str, Any]:
        """Chat-based web search fallback (uses coding plan quota)."""
        payload = {
            "model": DEFAULT_MODEL,
            "messages": [
                {"role": "user", "content": f"search for: {query}"}
            ],
            "tools": [
                {"type": "web_search", "web_search": {"enable": True, "search_result": True}}
            ],
            "stream": False,
        }

        try:
            data = self._post("chat/completions", payload, timeout=60)
        except (URLError, OSError) as exc:
            return self._error_result("web_search", f"Chat-based search failed: {exc}", query=query)

        # Extract the assistant's text reply
        choices = data.get("choices", [])
        if not choices:
            return self._error_result("web_search", "No choices in chat response", query=query, raw=data)

        message = choices[0].get("message", {})
        content = message.get("content", "")

        # Try to extract structured search results from the tool_calls or web_search_info
        results: list[dict[str, str]] = []
        web_search_info = data.get("web_search_info") or data.get("web_search_result")
        if isinstance(web_search_info, list):
            for item in web_search_info:
                results.append({
                    "title": item.get("title", ""),
                    "link": item.get("link", item.get("url", "")),
                    "content": item.get("content", item.get("snippet", "")),
                    "media": item.get("media", ""),
                })

        return {
            "ok": True,
            "method": "web_search",
            "query": query,
            "results": results,
            "synthesis": content,
            "source": "chat_fallback",
            "note": "Standalone search API unavailable (requires separate resource pack). Used chat-based synthesis instead.",
            "timestamp": time.time(),
            "usage": data.get("usage"),
        }

    # ------------------------------------------------------------------
    # 3. Zread — agent-style search + synthesis
    # ------------------------------------------------------------------

    def zread(self, query: str) -> dict[str, Any]:
        """Perform an agent-style search+synthesis via chat completions with web_search enabled.

        Unlike :meth:`web_search`, this returns a synthesized answer along with any
        search results the model chose to reference.

        Returns
        -------
        dict with keys: ok, method, query, answer, sources, usage
        """
        payload = {
            "model": DEFAULT_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a research assistant. Use web search to find accurate, "
                        "up-to-date information. Provide a comprehensive answer with "
                        "citations. Always cite your sources with URLs."
                    ),
                },
                {"role": "user", "content": query},
            ],
            "tools": [
                {"type": "web_search", "web_search": {"enable": True, "search_result": True}}
            ],
            "stream": False,
        }

        try:
            data = self._post("chat/completions", payload, timeout=90)
        except TimeoutError:
            return self._error_result("zread", "Request timed out (90s)", query=query)
        except (URLError, OSError) as exc:
            return self._error_result("zread", str(exc), query=query)

        choices = data.get("choices", [])
        if not choices:
            return self._error_result("zread", "No choices in response", query=query, raw=data)

        message = choices[0].get("message", {})
        answer = message.get("content", "")

        # Extract any referenced search results
        sources: list[dict[str, str]] = []
        web_search_info = data.get("web_search_info") or data.get("web_search_result")
        if isinstance(web_search_info, list):
            for item in web_search_info:
                sources.append({
                    "title": item.get("title", ""),
                    "link": item.get("link", item.get("url", "")),
                    "content": item.get("content", item.get("snippet", "")),
                    "media": item.get("media", ""),
                })

        # Parse inline citation patterns from the answer text as fallback
        if answer:
            # Extract URLs mentioned in the answer text
            url_pattern = re.compile(r'https?://[^\s\]\)>"]+')
            existing_links = {s.get("link", "") for s in sources}
            for url_match in url_pattern.finditer(answer):
                url = url_match.group(0).rstrip(".,;:)")
                if url not in existing_links:
                    sources.append({
                        "title": "",
                        "link": url,
                        "content": "",
                        "media": "",
                    })
                    existing_links.add(url)

            # Extract [ref_N] / [source_N] citation markers
            ref_pattern = re.compile(r'\[(?:ref|source)[_ ]?\d+\]', re.IGNORECASE)
            ref_markers = ref_pattern.findall(answer)
            if ref_markers:
                # Deduplicate
                seen = set()
                for marker in ref_markers:
                    if marker.lower() not in seen:
                        seen.add(marker.lower())
                        sources.append({
                            "title": f"Citation: {marker}",
                            "link": "",
                            "content": "",
                            "media": "",
                        })

        return {
            "ok": True,
            "method": "zread",
            "query": query,
            "answer": answer,
            "sources": sources,
            "usage": data.get("usage"),
            "model": data.get("model", DEFAULT_MODEL),
            "timestamp": time.time(),
        }


# ---------------------------------------------------------------------------
# CLI entry point — JSON output for agent parsing
# ---------------------------------------------------------------------------


def _json_output(result: dict[str, Any]) -> None:
    """Print a result dict as JSON and exit with appropriate code."""
    print(json.dumps(result, indent=2, ensure_ascii=False))
    sys.exit(0 if result.get("ok") else 1)


def main() -> None:
    """CLI entry point for ``python -m harness.web_tools``."""
    if len(sys.argv) < 3:
        prog = sys.argv[0] if sys.argv else "python -m harness.web_tools"
        print(json.dumps({
            "ok": False,
            "error": f"Usage: {prog} <search|reader|zread> <query_or_url>",
        }, indent=2))
        sys.exit(1)

    command = sys.argv[1].lower()
    argument = sys.argv[2]
    extra_args = sys.argv[3:]

    try:
        tools = WebTools()
    except RuntimeError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        sys.exit(1)

    if command == "search":
        # Optional: --engine and --count flags
        engine = "search_std"
        count = 10
        i = 0
        while i < len(extra_args):
            if extra_args[i] == "--engine" and i + 1 < len(extra_args):
                engine = extra_args[i + 1]
                i += 2
            elif extra_args[i] == "--count" and i + 1 < len(extra_args):
                count = int(extra_args[i + 1])
                i += 2
            else:
                i += 1
        _json_output(tools.web_search(argument, engine=engine, count=count))

    elif command == "reader":
        fmt = "markdown"
        i = 0
        while i < len(extra_args):
            if extra_args[i] == "--format" and i + 1 < len(extra_args):
                fmt = extra_args[i + 1]
                i += 2
            else:
                i += 1
        _json_output(tools.web_reader(argument, format=fmt))

    elif command == "zread":
        _json_output(tools.zread(argument))

    else:
        print(json.dumps({
            "ok": False,
            "error": f"Unknown command '{command}'. Use: search, reader, zread",
        }, indent=2))
        sys.exit(1)


if __name__ == "__main__":
    main()
