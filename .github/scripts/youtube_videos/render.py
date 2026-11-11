"""Render the video list as the HTML table injected into the README.

The markup is a plain ``<table>`` because GitHub sanitises ``<div>`` based
layouts but keeps table cells, so the two column grid survives the
markdown renderer. Every value that comes from YouTube is HTML escaped.
"""

from __future__ import annotations

import html
from typing import Sequence

from .models import Video, compact_number, format_date, format_duration

__all__ = ["CELL_WIDTH", "COLUMNS", "escape_text", "render_cards"]

#: The grid is three columns wide, so six videos fill two rows.
COLUMNS = 3

#: Width of a grid cell.
CELL_WIDTH = "33%"

#: Separator used between the metadata parts.
METADATA_SEPARATOR = " · "


def escape_text(value: str) -> str:
    """Escape a value for safe inclusion in HTML markup."""
    return html.escape(str(value), quote=True)


def _metadata_line(video: Video) -> str:
    """Build the metadata line shown under the title.

    Unknown parts are omitted; the remaining ones keep the order views,
    duration, date.

    The view count is a live counter, so the generated block differs on
    every run once a video gets an extra view. That is accepted on purpose:
    the workflow runs weekly and refreshing the counters is part of what the
    README is for. The cost is one commit per run instead of one commit per
    new upload.
    """
    parts = []
    if video.view_count is not None:
        parts.append(f"{compact_number(video.view_count)} visualizaciones")
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
