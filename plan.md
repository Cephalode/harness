# Implementation Plan: Caching Layer with TTL-Based Invalidation

## Goal

Add a configurable caching layer to the Harness orchestration system that caches agent responses (and intermediate delegation results) with TTL-based invalidation, reducing duplicate LLM calls and lowering cost/latency for repeated or similar tasks.

---

## Architecture Overview

```
User Message
     │
     ▼
┌──────────────┐
│  Orchestrator │
└──────┬───────┘
       │
       ▼
┌──────────────┐     ┌─────────────────┐
│  CacheLayer   │────►│  CacheBackend    │
│  (middleware)  │     │  (TTL store)     │
└──────┬───────┘     └─────────────────┘
       │
       ▼ (cache miss)
┌──────────────┐
│    Team       │──► Agent.run() ──► PI CLI
│  (lead/workers)│                    │
└──────────────┘                     │
       │                             │
       └─── result ──► CacheLayer ──► CacheBackend (store)
                         │
                         ▼
                      Response to User
```

### Key Design Decisions

1. **Cache is opt-in per agent/team via config** — not everything should be cached (e.g., creative tasks, validation reviews).
2. **Cache sits between Orchestrator→Team and Team→Agent delegation** — two interception points.
3. **Pluggable backends** — in-memory (default), file-based (JSON on disk), and Redis — selected via config.
4. **TTL per cache entry** — each cache key carries its own TTL; on read, expired entries are evicted.
5. **Semantic cache key** — derived from agent name + normalized message hash + model, not raw text (handles minor formatting differences).
6. **Cache-aware events** — `cache_hit` and `cache_miss` events emitted to EventBus for monitoring.
7. **Fallback on error** — if the cache backend fails, the request proceeds without caching (fail-open).

---

## Tasks

### Phase 1: Core Cache Infrastructure

1. **Create `harness/cache.py` — CacheBackend abstraction and implementations**
   - File: `harness/cache.py` (new)
   - Changes: Create the module with:
     - `CacheEntry` dataclass: `key`, `value`, `ttl_seconds`, `created_at`, `model`, `agent_name`, `team_name`, `metadata`
     - `CacheBackend` ABC with methods: `get(key)`, `set(key, entry)`, `delete(key)`, `clear()`, `cleanup_expired()`, `get_stats()`
     - `InMemoryCacheBackend` — dict-backed, thread-safe via asyncio.Lock, supports TTL eviction on read and periodic cleanup
     - `FileCacheBackend` — JSON file per entry under `cache/` directory, atomic writes, supports TTL
     - `RedisCacheBackend` — optional, requires `redis` package, uses Redis SET with EX TTL
     - `CacheKeyBuilder` — utility class that builds keys from `(agent_name, team_name, model, message_hash)` using SHA-256
   - Acceptance: Unit tests can create each backend, set/get entries with TTL, and verify expired entries return `None`.

2. **Create `harness/cache_config.py` — Cache configuration dataclasses**
   - File: `harness/cache_config.py` (new)
   - Changes: Define:
     - `CacheConfig` dataclass: `enabled: bool`, `backend: str` (`"memory"` | `"file"` | `"redis"`), `default_ttl: int` (seconds, default 300), `max_entries: int` (default 1000), `key_normalization: bool` (default `True`), `cache_dir: str` (default `"cache"`), `redis_url: str` (default `"redis://localhost:6379/0"`)
     - `AgentCacheConfig` dataclass: `agent_name: str`, `enabled: bool`, `ttl_override: int | None`, `cache_delegations: bool` (default `True`), `cache_responses: bool` (default `True`)
     - Parse functions: `parse_cache_config(yaml_data)` and `parse_agent_cache_configs(yaml_data)` that extract from YAML
   - Acceptance: Config parses correctly from YAML snippet; defaults fill in for missing fields.

3. **Extend `harness/config.py` — Add cache config to HarnessConfig**
   - File: `harness/config.py`
   - Changes:
     - Import `CacheConfig`, `AgentCacheConfig` from `harness.cache_config`
     - Add `cache: CacheConfig` field to `HarnessConfig` (default `CacheConfig()`)
     - Add `agent_cache: list[AgentCacheConfig]` field to `HarnessConfig` (default `[]`)
     - Parse `cache:` section from YAML in `load_config()`; if absent, defaults to disabled
     - Parse `agent_cache:` list from YAML
   - Acceptance: Existing configs without `cache:` section still load correctly; new section parses to `CacheConfig`.

### Phase 2: Cache Middleware Layer

4. **Create `harness/cache_middleware.py` — CacheLayer that intercepts Agent.run() calls**
   - File: `harness/cache_middleware.py` (new)
   - Changes:
     - `CacheLayer` class:
       - `__init__(cache_config: CacheConfig, agent_cache_configs: list[AgentCacheConfig], cache_backend: CacheBackend, event_bus: EventBus | None)`
       - `async get_or_compute(agent_name, team_name, model, message, context, compute_fn) → dict` — the core method:
         1. Check if caching is enabled for this agent (via `AgentCacheConfig`)
         2. Build cache key from `(agent_name, team_name, model, normalized_message)`
         3. Try `cache_backend.get(key)`
         4. If hit and not expired: emit `cache_hit` event, return cached value (update cost tracker with "saved" tokens)
         5. If miss: emit `cache_miss` event, call `compute_fn()`, store result with TTL, return result
         6. On cache backend error: log warning, fall through to compute_fn (fail-open)
       - `normalize_message(message: str) → str` — strip whitespace, lowercase, normalize timestamps/UUIDs
       - `should_cache(agent_name: str) → bool` — consult `AgentCacheConfig`
       - `get_ttl(agent_name: str) → int` — per-agent TTL override or default
       - `invalidate(pattern: str) → int` — delete entries matching a key pattern
       - `clear() → None` — clear entire cache
       - `get_stats() → dict` — cache hit/miss ratio, entry count, memory usage
     - Cache statistics tracking: `hits`, `misses`, `evictions`, `errors` counters
   - Acceptance: CacheLayer correctly passes through to compute_fn on miss; returns cached value on hit; emits events on hit/miss; fail-opens on backend error.

5. **Integrate CacheLayer into `Agent.run()`**
   - File: `harness/agent.py`
   - Changes:
     - Add `cache_layer: CacheLayer | None = None` parameter to `Agent.__init__()`
     - In `Agent.run()`, after building `system_prompt` and `prompt`, before calling `_execute_pi()`:
       ```python
       if self.cache_layer and self.cache_layer.should_cache(self.name):
           result = await self.cache_layer.get_or_compute(
               agent_name=self.name,
               team_name=self.team_name,
               model=self.model,
               message=message,
               context=context,
               compute_fn=lambda: self._execute_pi(cmd, prompt, timeout),
           )
       else:
           result = await self._execute_pi(cmd, prompt, timeout)
       ```
     - Note: `_execute_pi` needs to be called within `get_or_compute`, not as a pre-built coroutine, to avoid premature execution. Use a lambda or wrapper that returns an awaitable.
   - Acceptance: Agents with cache enabled hit the cache on repeated identical messages; agents without cache skip the layer entirely.

6. **Integrate CacheLayer into `Team.execute()` for delegation results**
   - File: `harness/team.py`
   - Changes:
     - Add `cache_layer: CacheLayer | None = None` parameter to `Team.__init__()`
     - In `Team.execute()`, when worker delegations produce results, check if `cache_layer.should_cache()` for each worker, and if so, wrap the `worker.run()` call through `cache_layer.get_or_compute()`
     - This caches intermediate delegation results, not just the final synthesized output
   - Acceptance: Worker delegation results are cached; repeated identical delegations within the TTL window return cached results.

7. **Integrate CacheLayer into `Orchestrator` initialization**
   - File: `harness/orchestrator.py`
   - Changes:
     - Import `CacheLayer` and backend factory
     - In `Orchestrator.__init__()`, create `CacheLayer` from config:
       ```python
       if config.cache.enabled:
           backend = create_cache_backend(config.cache)
           self.cache_layer = CacheLayer(config.cache, config.agent_cache, backend, event_bus)
       else:
           self.cache_layer = None
       ```
     - Pass `cache_layer` to each `Agent` and `Team` during construction
   - Acceptance: Orchestrator initializes cache when enabled; all agents/teams receive the shared cache layer.

### Phase 3: YAML Configuration

8. **Update `configs/multi_team.yaml` — Add cache configuration section**
   - File: `configs/multi_team.yaml`
   - Changes: Add a top-level `cache:` section:
     ```yaml
     cache:
       enabled: true
       backend: memory          # memory | file | redis
       default_ttl: 300         # 5 minutes
       max_entries: 1000
       key_normalization: true
       cache_dir: cache
       # redis_url: redis://localhost:6379/0
     
     agent_cache:
       - agent_name: orchestrator
         enabled: false           # orchestrator should always re-route
         cache_delegations: false
       - agent_name: planning_lead
         enabled: true
         ttl_override: 600       # 10 min — plans are stable
       - agent_name: planner
         enabled: true
         ttl_override: 600
       - agent_name: engineering_lead
         enabled: false           # leads should re-delegate each time
       - agent_name: frontend_dev
         enabled: true
         ttl_override: 180       # 3 min — code changes fast
       - agent_name: backend_dev
         enabled: true
         ttl_override: 180
       - agent_name: qa_engineer
         enabled: false           # QA should always re-evaluate
       - agent_name: security_reviewer
         enabled: false          # security must always re-check
       - agent_name: deep_researcher
         enabled: true
         ttl_override: 900       # 15 min — research data is stable
     ```
   - Acceptance: Config loads without errors; `load_config()` returns proper `CacheConfig` and `AgentCacheConfig`.

### Phase 4: Monitoring & Observability

9. **Add cache event types to `harness/events.py`**
   - File: `harness/events.py`
   - Changes: Document (no code change needed) that `HarnessEvent` already supports arbitrary `type` strings. The cache layer will emit events with types:
     - `"cache_hit"` — data: `{agent, team, key, ttl_remaining, model}`
     - `"cache_miss"` — data: `{agent, team, key, model}`
     - `"cache_expired"` — data: `{agent, team, key, age_seconds}`
     - `"cache_error"` — data: `{agent, team, key, error}`
     - `"cache_evicted"` — data: `{agent, team, key, reason}`
   - Acceptance: EventBus correctly handles these event types; dashboard can display them.

10. **Add cache stats to `harness/dashboard.py` API and CLI**
    - File: `harness/dashboard.py`
    - Changes:
      - Add `GET /api/cache/stats` endpoint returning cache hit/miss/eviction counts, entry count, memory usage
      - Add `DELETE /api/cache` endpoint to clear the cache
      - Add `GET /api/cache/entries` endpoint to list cache entries (key, agent, age, TTL remaining)
    - File: `harness/cli.py`
    - Changes:
      - Add `/cache` slash command that prints cache statistics
      - Add `/cache clear` to clear the cache
    - Acceptance: `GET /api/cache/stats` returns proper JSON; `/cache` command shows stats in CLI.

11. **Add cache-aware cost tracking in `harness/models.py`**
    - File: `harness/models.py`
    - Changes:
      - Add `savings_records: list[CostRecord]` to `CostTracker` for cache-hit savings
      - Add `record_savings(agent_name, team_name, model, saved_usage: TokenUsage)` method
      - Add `total_savings` property and `format_savings_summary()` method
      - When a cache hit occurs, record the estimated token savings from the cached result's usage data
    - Acceptance: `/cost` command in CLI shows both actual cost and estimated savings from cache hits.

### Phase 5: Cleanup & Maintenance

12. **Add periodic cache cleanup task**
    - File: `harness/cache.py`
    - Changes:
      - Add `CacheCleanupTask` — an async background task that runs `backend.cleanup_expired()` every `cleanup_interval` seconds (configurable, default 60)
      - Integrate into `Orchestrator` lifecycle: start on orchestrator init, stop on shutdown
    - File: `harness/orchestrator.py`
    - Changes:
      - Add `start_cache_cleanup()` and `stop_cache_cleanup()` methods
      - Call from CLI/dashboard lifecycle
    - Acceptance: Expired entries are cleaned up even if no one reads them.

13. **Add cache file-based persistence and recovery**
    - File: `harness/cache.py` (within `FileCacheBackend`)
    - Changes:
      - On startup, load existing cache files from `cache/` directory
      - Skip entries that are already expired (based on `created_at + ttl_seconds < now`)
      - Use atomic writes (already patterned in `state.py`) to prevent corruption
    - Acceptance: Restarting the harness preserves cached entries that haven't expired; expired entries are pruned on load.

14. **Update `harness/__init__.py` — Export new modules**
    - File: `harness/__init__.py`
    - Changes: Add `cache`, `cache_config`, `cache_middleware` to module exports
    - Acceptance: `from harness import CacheLayer, CacheConfig` works.

---

## Files to Modify

| File | Changes |
|------|---------|
| `harness/cache.py` | **New** — Cache backends (InMemory, File, Redis), CacheEntry, CacheKeyBuilder, CacheCleanupTask |
| `harness/cache_config.py` | **New** — CacheConfig and AgentCacheConfig dataclasses, YAML parsing |
| `harness/cache_middleware.py` | **New** — CacheLayer class (get_or_compute, should_cache, invalidate, stats) |
| `harness/config.py` | Add `cache: CacheConfig` and `agent_cache: list[AgentCacheConfig]` to HarnessConfig; parse from YAML |
| `harness/agent.py` | Add `cache_layer` param; wrap `run()` to check cache before executing PI call |
| `harness/team.py` | Add `cache_layer` param; wrap worker delegation calls through cache |
| `harness/orchestrator.py` | Create CacheLayer from config; pass to agents/teams; lifecycle methods for cleanup task |
| `harness/models.py` | Add `savings_records`, `record_savings()`, `total_savings`, `format_savings_summary()` to CostTracker |
| `harness/dashboard.py` | Add `/api/cache/stats`, `DELETE /api/cache`, `GET /api/cache/entries` endpoints |
| `harness/cli.py` | Add `/cache` and `/cache clear` slash commands |
| `harness/events.py` | No code change needed; cache events documented in comments |
| `harness/__init__.py` | Add cache module exports |
| `configs/multi_team.yaml` | Add `cache:` and `agent_cache:` configuration sections |
| `requirements.txt` | Add `redis>=5.0` as optional dependency (for Redis backend) |

## New Files

| File | Purpose |
|------|---------|
| `harness/cache.py` | Cache backends, CacheEntry dataclass, CacheKeyBuilder, periodic cleanup |
| `harness/cache_config.py` | Configuration dataclasses for cache settings |
| `harness/cache_middleware.py` | CacheLayer — the core middleware that intercepts agent calls |
| `harness/tests/test_cache.py` | Unit tests for all cache backends, CacheLayer, key normalization |
| `harness/tests/test_cache_middleware.py` | Integration tests for cache + Agent.run() |

---

## Dependencies

```
Task 1 (cache.py backends) ─┐
                             ├─► Task 4 (CacheLayer) ─► Task 5 (Agent integration) ─► Task 7 (Orchestrator) ─► Task 12 (cleanup task)
Task 2 (cache config)  ─────┤                          │
                             │                          ─► Task 6 (Team integration) ─► Task 7
Task 3 (config.py)      ────┘
                                                          
Task 8 (YAML config) ──── depends on Task 3
Task 9  (events) ──────── independent
Task 10 (dashboard) ───── depends on Task 4
Task 11 (cost savings) ── depends on Task 4
Task 13 (file persistence) depends on Task 1
Task 14 (exports) ──────── depends on Tasks 1,2,4
```

Phase 1 (Tasks 1-3) → Phase 2 (Tasks 4-7) → Phase 3 (Task 8) → Phase 4 (Tasks 9-11) → Phase 5 (Tasks 12-14)

---

## Cache Key Design

```
cache_key = sha256(
    agent_name + "|" +
    team_name + "|" +
    model + "|" +
    sha256(normalized_message) + "|" +
    sha256(normalized_context)
)
```

**Normalization rules** (when `key_normalization: true`):
- Strip leading/trailing whitespace
- Collapse multiple spaces/newlines to single space
- Lowercase for case-insensitive matching
- Remove UUIDs and timestamps (regex replace: `[0-9a-f]{8}-[0-9a-f]{4}-...` → `<uuid>`, ISO timestamps → `<timestamp>`)
- Strip conversation history section (only hash the new message + context)

This ensures that minor formatting differences and dynamic timestamps don't prevent cache hits.

---

## Configuration Examples

### Minimal (in-memory, 5-min TTL)
```yaml
cache:
  enabled: true
  backend: memory
  default_ttl: 300
```

### File-based with per-agent overrides
```yaml
cache:
  enabled: true
  backend: file
  default_ttl: 300
  max_entries: 5000
  cache_dir: cache

agent_cache:
  - agent_name: planner
    enabled: true
    ttl_override: 600
  - agent_name: qa_engineer
    enabled: false
```

### Redis for distributed harness
```yaml
cache:
  enabled: true
  backend: redis
  default_ttl: 300
  redis_url: redis://redis-host:6379/2

agent_cache:
  - agent_name: orchestrator
    enabled: false
```

---

## Testing Strategy

### Unit Tests (`harness/tests/test_cache.py`)

1. **InMemoryCacheBackend**: set/get, TTL expiry, cleanup, max_entries eviction, stats
2. **FileCacheBackend**: set/get, TTL expiry, atomic writes, corrupt file handling, load on startup
3. **RedisCacheBackend**: set/get, TTL (using Redis EX), connection failure fallback
4. **CacheKeyBuilder**: key generation, normalization, collision resistance

### Integration Tests (`harness/tests/test_cache_middleware.py`)

5. **CacheLayer.should_cache**: respects per-agent enabled/disabled config
6. **CacheLayer.get_or_compute**: hit path (no compute call), miss path (compute + store), TTL expiry
7. **CacheLayer + Agent.run()**: real agent call cached on second invocation with same message
8. **CacheLayer + Team.execute()**: delegation results cached across rounds
9. **Event emission**: cache_hit, cache_miss, cache_expired events appear in EventBus history
10. **Fail-open**: when backend raises exception, compute_fn is called and result returned

### End-to-End Tests

11. **Full pipeline**: CLI sends message → cache miss → agent runs → second identical message → cache hit → cost savings shown
12. **Dashboard API**: `GET /api/cache/stats` returns correct counts after cache operations
13. **Config reload**: change `cache.enabled` to false → subsequent runs skip cache

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| **Stale cached responses** — agent answers become outdated | Users get obsolete information | Per-agent TTL overrides (short TTL for code agents, longer for research); explicit `/cache clear` command; cache events visible in dashboard |
| **Cache key collisions** — different prompts hash to same key | Wrong response served | SHA-256 collision probability is negligible; include model + agent in key; cache entries store the original message for verification |
| **Memory pressure** — in-memory cache grows unbounded | OOM on long-running sessions | `max_entries` config with LRU eviction; periodic cleanup task; `CacheBackend.get_stats()` for monitoring |
| **File-based cache corruption** — crash during write | Partial cache files | Use atomic writes (write to `.tmp`, rename); load-time validation skips corrupt files |
| **Redis unavailable** — cache backend connection fails | Requests fail | Fail-open: catch `redis.exceptions.ConnectionError`, log warning, fall through to compute. `RedisCacheBackend.get()` returns `None` on error |
| **Conversation context drift** — same message in different conversation contexts gets same cached answer | Agent misses relevant prior context | Include `normalized_context` in cache key; option to disable caching for context-sensitive agents |
| **Security — cache poisoning** — malicious cache entries | Incorrect agent responses | Cache keys are content-addressed (SHA-256); no external write path to cache; file permissions restricted |
| **Race conditions on concurrent access** — two agents write same key | Cache corruption | `asyncio.Lock` in InMemory backend; Redis is naturally atomic; file backend uses atomic writes |
| **Performance overhead** — cache key computation on every call | Adds latency to non-cached calls | Key hashing is ~μs; normalization is minimal; skip entire cache layer when `cache.enabled = false` per agent |