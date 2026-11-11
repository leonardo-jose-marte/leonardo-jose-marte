"""Locate and replace the generated block inside the profile README.

The block lives between two HTML comment markers. Everything outside the
markers is preserved byte for byte, and the newline style of the file is
reused so a CRLF checkout does not turn into a mixed line ending file.
"""

from __future__ import annotations

__all__ = [
    "BEGIN_MARKER",
    "END_MARKER",
    "MarkersNotFound",
    "detect_newline",
    "extract_block",
    "replace_block",
]

BEGIN_MARKER = "<!-- BEGIN YOUTUBE-CARDS -->"
END_MARKER = "<!-- END YOUTUBE-CARDS -->"


class MarkersNotFound(Exception):
    """Raised when the README does not contain the expected marker pair."""


def detect_newline(text: str) -> str:
    """Return the dominant newline sequence used by ``text``."""
    crlf_count = text.count("\r\n")
    lf_count = text.count("\n") - crlf_count
    if crlf_count and crlf_count >= lf_count:
        return "\r\n"
    if lf_count:
        return "\n"
    if crlf_count:
        return "\r\n"
    return "\n"


def _normalize_newlines(text: str, newline: str) -> str:
    """Rewrite every newline in ``text`` to ``newline``."""
    unified = text.replace("\r\n", "\n").replace("\r", "\n")
    return unified.replace("\n", newline)


def extract_block(readme_text: str) -> str | None:
    """Return the content between the markers, or ``None`` when absent."""
    start = readme_text.find(BEGIN_MARKER)
    if start == -1:
        return None
    content_start = start + len(BEGIN_MARKER)
    end = readme_text.find(END_MARKER, content_start)
    if end == -1:
        return None
    return readme_text[content_start:end]


def replace_block(readme_text: str, new_block: str) -> str:
    """Replace the content between the markers with ``new_block``.

    The markers keep their own lines: the new content is surrounded by the
    newline style already used by the file.

    Raises:
        MarkersNotFound: when either marker is missing or out of order.
    """
    start = readme_text.find(BEGIN_MARKER)
    if start == -1:
        raise MarkersNotFound(f"Missing begin marker: {BEGIN_MARKER}")
    content_start = start + len(BEGIN_MARKER)
    end = readme_text.find(END_MARKER, content_start)
    if end == -1:
        raise MarkersNotFound(f"Missing end marker: {END_MARKER}")

    newline = detect_newline(readme_text)
    block = _normalize_newlines(new_block, newline).strip("\r\n")
    replacement = newline + block + newline
    return readme_text[:content_start] + replacement + readme_text[end:]
