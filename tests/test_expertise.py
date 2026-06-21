"""Tests for harness.expertise — per-agent expertise file management."""

import pytest

from harness.config import ExpertiseConfig
from harness.expertise import ExpertiseManager


class TestExpertiseManager:
    def _make_manager(self, tmp_path):
        return ExpertiseManager(base_dir=str(tmp_path))

    # ─── load ─────────────────────────────────────────────────

    def test_load_existing_file(self, tmp_path):
        exp_dir = tmp_path / "expertise"
        exp_dir.mkdir()
        (exp_dir / "agent.md").write_text("Agent knowledge", encoding="utf-8")
        mgr = self._make_manager(tmp_path)
        content = mgr.load(ExpertiseConfig(path="expertise/agent.md"))
        assert "Agent knowledge" in content

    def test_load_missing_file(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        content = mgr.load(ExpertiseConfig(path="nonexistent.md"))
        assert content == ""

    def test_load_enforces_max_lines(self, tmp_path):
        exp_dir = tmp_path / "expertise"
        exp_dir.mkdir()
        lines = [f"Line {i}" for i in range(20)]
        (exp_dir / "long.md").write_text("\n".join(lines), encoding="utf-8")

        mgr = self._make_manager(tmp_path)
        content = mgr.load(ExpertiseConfig(path="expertise/long.md", max_lines=5))
        loaded_lines = content.splitlines()
        assert len(loaded_lines) == 5
        # Should keep the LAST 5 lines
        assert "Line 19" in loaded_lines[-1]

    # ─── load_all ─────────────────────────────────────────────

    def test_load_all_multiple(self, tmp_path):
        exp_dir = tmp_path / "expertise"
        exp_dir.mkdir()
        (exp_dir / "a.md").write_text("Knowledge A", encoding="utf-8")
        (exp_dir / "b.md").write_text("Knowledge B", encoding="utf-8")

        mgr = self._make_manager(tmp_path)
        configs = [
            ExpertiseConfig(path="expertise/a.md"),
            ExpertiseConfig(path="expertise/b.md"),
        ]
        content = mgr.load_all(configs)
        assert "Knowledge A" in content
        assert "Knowledge B" in content

    def test_load_all_empty(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        content = mgr.load_all([ExpertiseConfig(path="missing.md")])
        assert content == ""

    # ─── update ───────────────────────────────────────────────

    def test_update_writes_content(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        cfg = ExpertiseConfig(path="expertise/new.md", updatable=True)
        mgr.update(cfg, "New knowledge content")
        assert (tmp_path / "expertise" / "new.md").exists()
        assert "New knowledge content" in (tmp_path / "expertise" / "new.md").read_text()

    def test_update_not_updatable(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        cfg = ExpertiseConfig(path="expertise/frozen.md", updatable=False)
        mgr.update(cfg, "Should not be written")
        assert not (tmp_path / "expertise" / "frozen.md").exists()

    def test_update_enforces_max_lines(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        cfg = ExpertiseConfig(path="expertise/capped.md", updatable=True, max_lines=3)
        lines = "\n".join(f"Line {i}" for i in range(10))
        mgr.update(cfg, lines)
        content = (tmp_path / "expertise" / "capped.md").read_text()
        assert len(content.splitlines()) == 3

    # ─── append_insight ──────────────────────────────────────

    def test_append_insight_to_existing(self, tmp_path):
        exp_dir = tmp_path / "expertise"
        exp_dir.mkdir()
        (exp_dir / "agent.md").write_text("Existing knowledge", encoding="utf-8")

        mgr = self._make_manager(tmp_path)
        cfg = ExpertiseConfig(path="expertise/agent.md", updatable=True)
        mgr.append_insight(cfg, "New insight")

        content = (exp_dir / "agent.md").read_text()
        assert "Existing knowledge" in content
        assert "New insight" in content

    def test_append_insight_to_empty(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        cfg = ExpertiseConfig(path="expertise/new.md", updatable=True)
        mgr.append_insight(cfg, "First insight")
        content = (tmp_path / "expertise" / "new.md").read_text()
        assert "First insight" in content

    def test_append_insight_not_updatable(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        cfg = ExpertiseConfig(path="expertise/frozen.md", updatable=False)
        mgr.append_insight(cfg, "Should not be added")
        assert not (tmp_path / "expertise" / "frozen.md").exists()

    # ─── format_expertise_section ─────────────────────────────

    def test_format_with_content(self, tmp_path):
        exp_dir = tmp_path / "expertise"
        exp_dir.mkdir()
        (exp_dir / "agent.md").write_text("Domain knowledge", encoding="utf-8")

        mgr = self._make_manager(tmp_path)
        configs = [ExpertiseConfig(path="expertise/agent.md")]
        section = mgr.format_expertise_section(configs)
        assert "Expertise" in section
        assert "Domain knowledge" in section

    def test_format_empty(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        configs = [ExpertiseConfig(path="nonexistent.md")]
        section = mgr.format_expertise_section(configs)
        assert section == ""

    # ─── get_agent_names ──────────────────────────────────────

    def test_get_agent_names(self, tmp_path):
        exp_dir = tmp_path / "expertise"
        exp_dir.mkdir()
        (exp_dir / "agent1.md").write_text("a1", encoding="utf-8")
        (exp_dir / "agent2.md").write_text("a2", encoding="utf-8")
        (exp_dir / "notes.txt").write_text("not an agent", encoding="utf-8")

        mgr = self._make_manager(tmp_path)
        names = mgr.get_agent_names()
        assert "agent1" in names
        assert "agent2" in names
        assert "notes" not in names  # .txt not included

    def test_get_agent_names_no_dir(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        assert mgr.get_agent_names() == []
