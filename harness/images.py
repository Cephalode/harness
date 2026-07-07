"""Image handling for vision-capable agents.

Extracts image URLs/references from messages, downloads them to temporary
local files (PI CLI requires local @file paths for images), and manages
their lifecycle.

Supported image sources:
  - Markdown: ![alt](url)
  - Bare URLs: https://...png, .jpg, .jpeg, .gif, .webp, .svg, .bmp
  - Local file paths: /absolute/path.png, ./relative/path.png
"""
from __future__ import annotations

import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Patterns for detecting image references in messages
IMAGE_PATTERNS = [
    re.compile(r'!\[[^\]]*\]\(([^)]+)\)'),                                    # markdown images
    re.compile(r'(https?://\S+\.(?:png|jpg|jpeg|gif|webp|svg|bmp))', re.I),   # bare URLs
]

# Supported image extensions (what PI CLI accepts)
IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.bmp'}


def extract_image_refs(message: str) -> list[str]:
    """Extract image URLs and local file paths from a message.

    Returns a deduplicated list preserving order of first appearance.
    """
    seen: set[str] = set()
    refs: list[str] = []

    for pattern in IMAGE_PATTERNS:
        for match in pattern.finditer(message):
            ref = match.group(1).strip()
            if ref not in seen:
                seen.add(ref)
                refs.append(ref)

    # Also detect local file paths (absolute or starting with ./)
    for word in message.split():
        # Strip trailing punctuation
        cleaned = word.rstrip('.,;:)]>')
        if any(cleaned.lower().endswith(ext) for ext in IMAGE_EXTENSIONS):
            if cleaned not in seen:
                if cleaned.startswith('/') or cleaned.startswith('./') or cleaned.startswith('~/'):
                    seen.add(cleaned)
                    refs.append(cleaned)

    return refs


def is_url(ref: str) -> bool:
    """Check if a reference is a URL."""
    return ref.startswith('http://') or ref.startswith('https://')


def is_local_file(ref: str) -> bool:
    """Check if a reference points to an existing local file."""
    expanded = os.path.expanduser(ref)
    if not os.path.isabs(expanded):
        return False
    return os.path.isfile(expanded)


async def download_image(url: str, dest_dir: str | None = None) -> str | None:
    """Download an image URL to a local temp file.

    Returns the path to the downloaded file, or None on failure.
    """
    import aiohttp

    dest_dir = dest_dir or tempfile.mkdtemp(prefix="harness_img_")

    # Determine extension from URL
    parsed = urlparse(url)
    path = parsed.path.lower()
    ext = '.png'
    for candidate in ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.bmp']:
        if path.endswith(candidate):
            ext = candidate
            break

    # Create a safe filename
    import hashlib
    url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
    filename = f"img_{url_hash}{ext}"
    filepath = os.path.join(dest_dir, filename)

    if os.path.exists(filepath):
        return filepath

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status != 200:
                    logger.warning("Failed to download image %s: HTTP %d", url, resp.status)
                    return None
                body = await resp.read()
                with open(filepath, 'wb') as f:
                    f.write(body)
                logger.info("Downloaded image %s → %s (%d bytes)", url[:80], filepath, len(body))
                return filepath
    except Exception as exc:
        logger.warning("Failed to download image %s: %s", url[:80], exc)
        return None


async def resolve_image_refs(
    refs: list[str],
    download_dir: str | None = None,
) -> list[str]:
    """Resolve image references to local file paths.

    - Local files are verified and returned as-is
    - URLs are downloaded to temp files
    - Invalid/missing refs are silently dropped

    Returns list of absolute local file paths.
    """
    resolved: list[str] = []

    for ref in refs:
        if is_local_file(ref):
            resolved.append(os.path.expanduser(ref))
        elif is_url(ref):
            path = await download_image(ref, download_dir)
            if path:
                resolved.append(path)
        else:
            logger.debug("Skipping unrecognized image ref: %s", ref[:80])

    return resolved


def cleanup_temp_images(paths: list[str]) -> None:
    """Remove downloaded temp image files (best-effort)."""
    for path in paths:
        try:
            if path.startswith(tempfile.gettempdir()) and os.path.isfile(path):
                os.unlink(path)
        except OSError:
            pass
