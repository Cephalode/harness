"""Tests for harness.images — image reference extraction and handling."""

import os
import pytest

from harness.images import (
    extract_image_refs,
    is_url,
    is_local_file,
    strip_images_from_message,
    encode_image_paths,
    decode_image_paths,
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


# ─── strip_images_from_message ────────────────────────────────

class TestStripImagesFromMessage:
    def test_strips_markdown_images(self):
        msg = "Check ![alt text](https://example.com/img.png) for details"
        stripped = strip_images_from_message(msg)
        assert "alt text" in stripped
        assert "https://example.com/img.png" not in stripped

    def test_strips_bare_urls_on_own_line(self):
        msg = "See this:\nhttps://example.com/img.png\nfor details"
        stripped = strip_images_from_message(msg)
        assert "https://example.com/img.png" not in stripped
        assert "details" in stripped

    def test_preserves_inline_urls(self):
        # Bare URLs inline (not on own line) may or may not be stripped
        # The regex uses ^ and $ anchors, so inline should be preserved
        msg = "Visit https://example.com/img.png for reference"
        stripped = strip_images_from_message(msg)
        # Inline URLs are not stripped (regex anchors to line start/end)
        assert "https://example.com" in stripped

    def test_no_images_unchanged(self):
        msg = "Just regular text"
        assert strip_images_from_message(msg) == msg


# ─── encode/decode image paths ────────────────────────────────

class TestEncodeDecodeImagePaths:
    def test_encode_single_path(self):
        result = encode_image_paths(["/tmp/img.png"])
        assert "<<IMAGE_PATHS:" in result
        assert "/tmp/img.png" in result
        assert result.endswith(">>")

    def test_encode_multiple_paths(self):
        result = encode_image_paths(["/tmp/a.png", "/tmp/b.jpg"])
        assert "/tmp/a.png" in result
        assert "/tmp/b.jpg" in result

    def test_encode_empty(self):
        assert encode_image_paths([]) == ""

    def test_decode_single_path(self):
        context = "Some text <<IMAGE_PATHS:/tmp/img.png>> more text"
        paths = decode_image_paths(context)
        assert paths == ["/tmp/img.png"]

    def test_decode_multiple_paths(self):
        context = "<<IMAGE_PATHS:/tmp/a.png,/tmp/b.jpg>>"
        paths = decode_image_paths(context)
        assert paths == ["/tmp/a.png", "/tmp/b.jpg"]

    def test_decode_no_marker(self):
        paths = decode_image_paths("No image paths here")
        assert paths == []

    def test_roundtrip(self):
        original = ["/tmp/img1.png", "/tmp/img2.jpg"]
        encoded = encode_image_paths(original)
        decoded = decode_image_paths(encoded)
        assert decoded == original
