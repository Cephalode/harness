"""Tests for harness.skills — skill file loading."""

import pytest
from pathlib import Path

from harness.skills import SkillLoader


class TestSkillLoader:
    def test_load_existing_file(self, tmp_path):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "coding.md").write_text("# Coding Skill\nWrite good code.", encoding="utf-8")

        loader = SkillLoader(base_dir=str(tmp_path))
        content = loader.load("skills/coding.md")
        assert "Coding Skill" in content
        assert "Write good code" in content

    def test_load_missing_file(self, tmp_path):
        loader = SkillLoader(base_dir=str(tmp_path))
        content = loader.load("nonexistent.md")
        assert "not found" in content

    def test_load_many(self, tmp_path):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "a.md").write_text("Skill A content", encoding="utf-8")
        (skills_dir / "b.md").write_text("Skill B content", encoding="utf-8")

        loader = SkillLoader(base_dir=str(tmp_path))
        result = loader.load_many(["skills/a.md", "skills/b.md"])
        assert "Skill: a" in result
        assert "Skill: b" in result
        assert "Skill A content" in result
        assert "Skill B content" in result
        assert "---" in result

    def test_load_many_empty(self, tmp_path):
        loader = SkillLoader(base_dir=str(tmp_path))
        assert loader.load_many([]) == ""

    def test_list_available(self, tmp_path):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "coding.md").write_text("code", encoding="utf-8")
        (skills_dir / "review.md").write_text("review", encoding="utf-8")
        (skills_dir / "notes.txt").write_text("not a skill", encoding="utf-8")

        loader = SkillLoader(base_dir=str(tmp_path))
        available = loader.list_available()
        assert len(available) == 2
        assert all(s.endswith(".md") for s in available)

    def test_list_available_no_dir(self, tmp_path):
        loader = SkillLoader(base_dir=str(tmp_path))
        assert loader.list_available() == []

    def test_absolute_path_load(self, tmp_path):
        f = tmp_path / "abs_skill.md"
        f.write_text("Absolute skill content", encoding="utf-8")
        loader = SkillLoader(base_dir=str(tmp_path))
        content = loader.load(str(f))
        assert "Absolute skill content" in content
