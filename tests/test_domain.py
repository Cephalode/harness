"""Tests for harness.domain — file permission enforcement."""

import pytest
from pathlib import Path

from harness.config import DomainConfig
from harness.domain import DomainEnforcer


class TestDomainEnforcer:
    def test_full_read_access(self, tmp_path):
        """Domain with read=['.'] grants access to everything."""
        de = DomainEnforcer(DomainConfig(read=["."]), base_dir=str(tmp_path))
        assert de.can_read("src/main.py") is True
        assert de.can_read("README.md") is True

    def test_restricted_read_access(self, tmp_path):
        de = DomainEnforcer(
            DomainConfig(read=["src", "docs"]),
            base_dir=str(tmp_path),
        )
        # Create dirs so they exist for resolution
        (tmp_path / "src").mkdir()
        (tmp_path / "docs").mkdir()
        (tmp_path / "secrets").mkdir()

        assert de.can_read("src/main.py") is True
        assert de.can_read("docs/guide.md") is True
        assert de.can_read("secrets/key.pem") is False

    def test_write_access(self, tmp_path):
        de = DomainEnforcer(
            DomainConfig(read=["."], update=["src"]),
            base_dir=str(tmp_path),
        )
        (tmp_path / "src").mkdir()
        (tmp_path / "config").mkdir()

        assert de.can_write("src/file.py") is True
        assert de.can_write("config/settings.json") is False

    def test_no_write_access(self, tmp_path):
        de = DomainEnforcer(
            DomainConfig(read=["."], update=[]),
            base_dir=str(tmp_path),
        )
        assert de.can_write("anything.txt") is False

    def test_filter_writes(self, tmp_path):
        de = DomainEnforcer(
            DomainConfig(read=["."], update=["src"]),
            base_dir=str(tmp_path),
        )
        (tmp_path / "src").mkdir()
        (tmp_path / "build").mkdir()

        paths = ["src/a.py", "src/b.py", "build/output.js", "config.json"]
        filtered = de.filter_writes(paths)
        assert filtered == ["src/a.py", "src/b.py"]

    def test_absolute_path(self, tmp_path):
        de = DomainEnforcer(
            DomainConfig(read=["src"]),
            base_dir=str(tmp_path),
        )
        (tmp_path / "src").mkdir()
        assert de.can_read(str(tmp_path / "src" / "file.py")) is True

    def test_format_domain_rules(self):
        de = DomainEnforcer(
            DomainConfig(read=["src", "docs"], update=["src"]),
        )
        rules = de.format_domain_rules()
        assert "src, docs" in rules
        assert "src" in rules
        assert "Domain Permissions" in rules

    def test_format_domain_rules_empty(self):
        de = DomainEnforcer(DomainConfig(read=[], update=[]))
        rules = de.format_domain_rules()
        assert "none" in rules
