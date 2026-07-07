"""Tests for harness.images — image reference extraction and handling."""

import os
import pytest

from harness.images import (
    extract_image_refs,
    is_url,
    is_local_file,
    IMAGE_EXTENSIONS,
)


# ─── extract_image_refs ───────────────────────────────────────

class TestExtractImageRefs:
    def test_markdown_image(self):
        msg = "Check this ![screenshot](https://example.com/img.png)"
        refs = extract_image_refs(msg)
        assert len(refs) == 1
        assert refs[0] == "https://example.com/img.png"

    def test_bare_url(self):
        msg = "Look at https://example.com/photo.jpg for reference"
        refs = extract_image_refs(msg)
        assert len(refs) == 1
        assert "photo.jpg" in refs[0]

    def test_multiple_refs(self):
        msg = (
            "![img1](https://a.com/1.png) and "
            "![img2](https://b.com/2.jpg)"
        )
        refs = extract_image_refs(msg)
        assert len(refs) == 2

    def test_deduplication(self):
        msg = "![same](https://example.com/img.png) and ![also](https://example.com/img.png)"
        refs = extract_image_refs(msg)
        assert len(refs) == 1

    def test_local_absolute_path(self):
        msg = "See /tmp/screenshot.png for details"
        refs = extract_image_refs(msg)
        assert "/tmp/screenshot.png" in refs

    def test_local_relative_path(self):
        msg = "See ./images/photo.jpg for details"
        refs = extract_image_refs(msg)
        assert "./images/photo.jpg" in refs

    def test_home_path(self):
        msg = "See ~/Pictures/test.png"
        refs = extract_image_refs(msg)
        assert "~/Pictures/test.png" in refs

    def test_no_images(self):
        msg = "Just a regular message with no images"
        refs = extract_image_refs(msg)
        assert refs == []

    def test_various_extensions(self):
        for ext in [".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp"]:
            msg = f"Image: https://example.com/test{ext}"
            refs = extract_image_refs(msg)
            assert len(refs) == 1, f"Failed for extension {ext}"


# ─── is_url ───────────────────────────────────────────────────

class TestIsUrl:
    def test_http(self):
        assert is_url("http://example.com/img.png") is True

    def test_https(self):
        assert is_url("https://example.com/img.png") is True

    def test_local_path(self):
        assert is_url("/tmp/img.png") is False

    def test_relative_path(self):
        assert is_url("./img.png") is False


# ─── is_local_file ────────────────────────────────────────────

class TestIsLocalFile:
    def test_existing_file(self, tmp_path):
        f = tmp_path / "test.png"
        f.write_text("fake image")
        assert is_local_file(str(f)) is True

    def test_nonexistent_file(self):
        assert is_local_file("/nonexistent/path/img.png") is False

    def test_relative_path_not_absolute(self):
        assert is_local_file("./img.png") is False

    def test_home_expansion(self, tmp_path):
        # Create a file and test with ~/path style (can't easily test without home setup)
        # Just test the negative case
        assert is_local_file("~/nonexistent_xyz/img.png") is False
