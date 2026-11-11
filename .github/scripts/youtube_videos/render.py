"""Render the video list as the HTML table injected into the README.

The markup is a plain ``<table>`` because GitHub sanitises ``<div>`` based
layouts but keeps table cells, so the two column grid survives the
markdown renderer. Every value that comes from YouTube is HTML escaped.
"""

from __future__ import annotations

import html
from typing import Sequence

from .models import Video, format_date, format_duration

__all__ = ["CELL_WIDTH", "COLUMNS", "escape_text", "render_cards"]

#: The grid is two columns wide.
COLUMNS = 2

#: Width of a grid cell.
CELL_WIDTH = "50%"

#: Separator used between the metadata parts.
METADATA_SEPARATOR = " · "


def escape_text(value: str) -> str:
    """Escape a value for safe inclusion in HTML markup."""
    return html.escape(str(value), quote=True)


def _metadata_line(video: Video) -> str:
    """Build the metadata line shown under the title.

    Unknown parts are omitted; the remaining ones keep the order duration,
    date. The view count is deliberately NOT rendered: it is a live counter
    that changes between two runs of the script, which would make the
    generated block differ every time and defeat the "commit only when the
    block actually changed" rule. The value remains available in the JSON
    summary.
    """
    parts = []
    if video.duration_seconds is not None:
        parts.append(format_duration(video.duration_seconds))
    parts.append(format_date(video.published_at))
    return METADATA_SEPARATOR.join(parts)


def _render_cell(video: Video) -> list[str]:
    """Render a single table cell."""
    url = escape_text(f"https://youtu.be/{video.video_id}")
    thumbnail = escape_text(video.thumbnail_url)
    title = escape_text(video.title)
    return [
        f'    <td width="{CELL_WIDTH}" valign="top">',
        f'      <a href="{url}"><img src="{thumbnail}" alt="{title}" width="100%" /></a><br />',
        f'      <a href="{url}"><strong>{title}</strong></a><br />',
        f"      <sub>{escape_text(_metadata_line(video))}</sub>",
        "    </td>",
    ]


def render_cards(videos: Sequence[Video]) -> str:
    """Render the videos as a two column HTML table.

    Rows are filled with two cells each; the last row holds the remaining
    videos when the total is not a multiple of two.
    """
    lines = ["<table>"]
    for start in range(0, len(videos), COLUMNS):
        lines.append("  <tr>")
        for video in videos[start : start + COLUMNS]:
            lines.extend(_render_cell(video))
        lines.append("  </tr>")
    lines.append("</table>")
    return "\n".join(lines)
