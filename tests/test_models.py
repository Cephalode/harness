"""Tests for harness.models — cost tracking, token usage, and parsing."""

import pytest
from harness.models import (
    CostRecord,
    CostTracker,
    TokenUsage,
    MODEL_PRICING,
    parse_usage_from_pi_output,
)


# ─── TokenUsage ────────────────────────────────────────────────

class TestTokenUsage:
    def test_defaults(self):
        u = TokenUsage()
        assert u.input_tokens == 0
        assert u.output_tokens == 0
        assert u.cache_creation_input_tokens == 0
        assert u.cache_read_input_tokens == 0

    def test_custom_values(self):
        u = TokenUsage(input_tokens=100, output_tokens=200,
                       cache_creation_input_tokens=50, cache_read_input_tokens=75)
        assert u.input_tokens == 100
        assert u.output_tokens == 200


# ─── CostTracker ───────────────────────────────────────────────

class TestCostTracker:
    def _make_tracker(self):
        return CostTracker()

    def test_record_returns_cost_record(self):
        ct = self._make_tracker()
        usage = TokenUsage(input_tokens=1_000_000, output_tokens=1_000_000)
        rec = ct.record("agent1", "team1", "gpt-4o", usage)
        assert isinstance(rec, CostRecord)
        assert rec.agent_name == "agent1"
        assert rec.team_name == "team1"
        assert rec.model == "gpt-4o"
        assert rec.cost_usd > 0

    def test_total_cost_empty(self):
        ct = self._make_tracker()
        assert ct.total_cost == 0.0

    def test_total_cost_accumulates(self):
        ct = self._make_tracker()
        usage = TokenUsage(input_tokens=1_000_000, output_tokens=0)
        ct.record("a", None, "gpt-4o", usage)
        ct.record("b", None, "gpt-4o", usage)
        # 2 records × $2.50 input cost each = $5.00
        assert ct.total_cost == pytest.approx(5.0, abs=0.01)

    def test_total_usage(self):
        ct = self._make_tracker()
        ct.record("a", None, "gpt-4o", TokenUsage(input_tokens=100, output_tokens=50))
        ct.record("b", None, "gpt-4o", TokenUsage(input_tokens=200, output_tokens=75))
        total = ct.total_usage
        assert total.input_tokens == 300
        assert total.output_tokens == 125

    def test_cost_by_team(self):
        ct = self._make_tracker()
        usage = TokenUsage(input_tokens=1_000_000, output_tokens=0)
        ct.record("a", "team_a", "gpt-4o", usage)
        ct.record("b", "team_b", "gpt-4o", usage)
        ct.record("c", None, "gpt-4o", usage)
        by_team = ct.cost_by_team()
        assert "team_a" in by_team
        assert "team_b" in by_team
        assert None in by_team

    def test_cost_by_agent(self):
        ct = self._make_tracker()
        usage = TokenUsage(input_tokens=1_000_000, output_tokens=0)
        ct.record("alpha", "t", "gpt-4o", usage)
        ct.record("beta", "t", "gpt-4o", usage)
        ct.record("alpha", "t", "gpt-4o", usage)
        by_agent = ct.cost_by_agent()
        assert by_agent["alpha"] == pytest.approx(by_agent["beta"] * 2, abs=0.01)

    def test_format_summary(self):
        ct = self._make_tracker()
        ct.record("a", "team1", "gpt-4o", TokenUsage(input_tokens=1000, output_tokens=500))
        summary = ct.format_summary()
        assert "Total Cost" in summary
        assert "By Agent" in summary
        assert "By Team" in summary


# ─── Cost calculation with model pricing ───────────────────────

class TestCalculateCost:
    """Test _calculate_cost indirectly through CostTracker.record."""

    def _cost(self, model, usage):
        ct = CostTracker()
        rec = ct.record("x", None, model, usage)
        return rec.cost_usd

    @pytest.mark.parametrize("model_key", [
        "gpt-4o", "gpt-4o-mini", "claude-sonnet-4-6",
        "gemini-2.5-pro", "gemini-2.5-flash",
    ])
    def test_known_models_return_positive_cost(self, model_key):
        usage = TokenUsage(input_tokens=1_000_000, output_tokens=1_000_000)
        cost = self._cost(model_key, usage)
        pricing = MODEL_PRICING[model_key]
        expected = pricing["input"] + pricing["output"]
        assert cost == pytest.approx(expected, rel=0.01)

    def test_free_models(self):
        for model in ["glm-5.1", "glm-4.7", "qwen3.5:latest"]:
            usage = TokenUsage(input_tokens=1_000_000, output_tokens=1_000_000)
            assert self._cost(model, usage) == 0.0

    def test_provider_prefix_stripped(self):
        """z-ai/glm-5.1 should resolve to glm-5.1 pricing (free)."""
        usage = TokenUsage(input_tokens=1_000_000, output_tokens=1_000_000)
        assert self._cost("z-ai/glm-5.1", usage) == 0.0

    def test_unknown_model_uses_default(self):
        usage = TokenUsage(input_tokens=1_000_000, output_tokens=1_000_000)
        cost = self._cost("unknown-model-xyz", usage)
        default = MODEL_PRICING["default"]
        expected = default["input"] + default["output"]
        assert cost == pytest.approx(expected, rel=0.01)

    def test_cache_tokens_cheaper(self):
        """Cache creation costs 1.25x input price; cache read costs 0.1x."""
        usage_normal = TokenUsage(input_tokens=1_000_000, output_tokens=0)
        usage_cache = TokenUsage(
            input_tokens=0, output_tokens=0,
            cache_creation_input_tokens=1_000_000,
        )
        normal_cost = self._cost("gpt-4o", usage_normal)
        cache_cost = self._cost("gpt-4o", usage_cache)
        assert cache_cost == pytest.approx(normal_cost * 1.25, rel=0.01)

    def test_zero_usage(self):
        assert self._cost("gpt-4o", TokenUsage()) == 0.0


# ─── parse_usage_from_pi_output ────────────────────────────────

class TestParseUsage:
    def test_full_output(self):
        output = {
            "usage": {
                "input": 20,
                "output": 74,
                "cacheRead": 11968,
                "cacheWrite": 0,
            }
        }
        usage = parse_usage_from_pi_output(output)
        assert usage.input_tokens == 20
        assert usage.output_tokens == 74
        assert usage.cache_read_input_tokens == 11968
        assert usage.cache_creation_input_tokens == 0

    def test_missing_usage(self):
        usage = parse_usage_from_pi_output({})
        assert usage.input_tokens == 0
        assert usage.output_tokens == 0

    def test_partial_usage(self):
        usage = parse_usage_from_pi_output({"usage": {"input": 100}})
        assert usage.input_tokens == 100
        assert usage.output_tokens == 0

    def test_none_usage(self):
        usage = parse_usage_from_pi_output({"usage": None})
        assert usage.input_tokens == 0
