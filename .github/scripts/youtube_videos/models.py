"""Domain models and pure formatting helpers for the YouTube video cards.

Everything in this module is standard library only and free of side effects,
so the helpers can be unit tested without touching the network.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Optional

__all__ = [
    "Video",
    "MONTH_ABBREVIATIONS_ES",
    "SHORT_MAX_DURATION_SECONDS",
    "SHORT_UNAMBIGUOUS_MAX_SECONDS",
    "parse_iso8601_duration",
    "format_duration",
    "compact_number",
    "format_date",
    "is_short_video",
    "is_live_video",
    "sort_videos",
]

#: Spanish short month names used by the rendered metadata line.
MONTH_ABBREVIATIONS_ES = (
    "ene",
    "feb",
    "mar",
    "abr",
    "may",
    "jun",
    "jul",
    "ago",
    "sep",
    "oct",
    "nov",
    "dic",
)

#: Official YouTube Shorts ceiling: 3 minutes.
SHORT_MAX_DURATION_SECONDS = 180

#: Videos at or below this length are treated as Shorts even when the API
#: exposes no ``shortsAspectRatio`` hint.
SHORT_UNAMBIGUOUS_MAX_SECONDS = 60

#: ``liveBroadcastContent`` values that mark a non-regular video.
LIVE_BROADCAST_VALUES = frozenset({"live", "upcoming"})

_DURATION_PATTERN = re.compile(
    r"^P"
    r"(?:(?P<years>\d+(?:\.\d+)?)Y)?"
    r"(?:(?P<months>\d+(?:\.\d+)?)M)?"
    r"(?:(?P<weeks>\d+(?:\.\d+)?)W)?"
    r"(?:(?P<days>\d+(?:\.\d+)?)D)?"
    r"(?:T"
    r"(?:(?P<hours>\d+(?:\.\d+)?)H)?"
    r"(?:(?P<minutes>\d+(?:\.\d+)?)M)?"
    r"(?:(?P<seconds>\d+(?:\.\d+)?)S)?"
    r")?$"
)


@dataclass(frozen=True)
class Video:
    """A single YouTube video as rendered in the README card grid."""

    video_id: str
    title: str
    published_at: datetime
    thumbnail_url: str
    duration_seconds: Optional[int] = None
    view_count: Optional[int] = None
    like_count: Optional[int] = None
    is_short: bool = False
    is_live: bool = False


def parse_iso8601_duration(value: str) -> int:
    """Convert an ISO 8601 duration such as ``PT1H6M56S`` into seconds.

    Raises:
        ValueError: if the value is not a valid ISO 8601 duration.
    """
    if not isinstance(value, str):
        raise ValueError(f"Invalid ISO 8601 duration: {value!r}")

    match = _DURATION_PATTERN.match(value.strip())
    if match is None:
        raise ValueError(f"Invalid ISO 8601 duration: {value!r}")

    parts = match.groupdict()
    if all(part is None for part in parts.values()):
        raise ValueError(f"Invalid ISO 8601 duration: {value!r}")

    total = (
        float(parts["years"] or 0) * 365 * 86_400
        + float(parts["months"] or 0) * 30 * 86_400
        + float(parts["weeks"] or 0) * 7 * 86_400
        + float(parts["days"] or 0) * 86_400
        + float(parts["hours"] or 0) * 3_600
        + float(parts["minutes"] or 0) * 60
        + float(parts["seconds"] or 0)
    )
    return int(total)


def format_duration(seconds: int) -> str:
    """Format a duration in seconds as ``M:SS`` or ``H:MM:SS``."""
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3_600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def compact_number(number: int) -> str:
    """Format a count compactly: ``999`` -> ``999``, ``1234`` -> ``1.2K``."""
    value = int(number)
    if value < 0:
        return str(value)
    if value < 1_000:
        return str(value)
    if value >= 1_000_000_000:
        return _compact_scaled(value / 1_000_000_000, "B")
    if value >= 1_000_000:
        return _compact_scaled(value / 1_000_000, "M")
    if value / 1_000 >= 999.95:
        # Rounding would push the value into the next magnitude.
        return _compact_scaled(value / 1_000_000, "M")
    return _compact_scaled(value / 1_000, "K")


def _compact_scaled(value: float, suffix: str) -> str:
    text = f"{value:.1f}"
    if text.endswith(".0"):
        text = text[:-2]
    return f"{text}{suffix}"


def format_date(moment: datetime) -> str:
    """Format a datetime as a Spanish short date, e.g. ``10 nov 2026``.

    Naive datetimes are assumed to be UTC; aware datetimes are converted to
    UTC so the rendered date is stable regardless of the source timezone.
    """
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    moment = moment.astimezone(timezone.utc)
    month = MONTH_ABBREVIATIONS_ES[moment.month - 1]
    return f"{moment.day} {month} {moment.year}"


def is_live_video(live_broadcast_content: Optional[str]) -> bool:
    """Return whether a video is a live or upcoming broadcast."""
    if not live_broadcast_content:
        return False
    return live_broadcast_content.strip().lower() in LIVE_BROADCAST_VALUES


def is_short_video(
    duration_seconds: Optional[int], has_shorts_aspect_ratio: bool = False
) -> bool:
    """Return whether a video looks like a Short.

    The official rule is "square or vertical aspect ratio AND up to 3
    minutes", but only the duration half is observable through the public
    API. A video is therefore treated as a Short when it is at most
    :data:`SHORT_MAX_DURATION_SECONDS` long and either carries a
    ``shortsAspectRatio`` thumbnail hint or is unambiguously tiny
    (:data:`SHORT_UNAMBIGUOUS_MAX_SECONDS` or less). Ambiguous videos in
    between are kept to avoid false positives.
    """
    if duration_seconds is None:
        return False
    if duration_seconds > SHORT_MAX_DURATION_SECONDS:
        return False
    return bool(has_shorts_aspect_ratio) or duration_seconds <= SHORT_UNAMBIGUOUS_MAX_SECONDS


def sort_videos(videos: Iterable[Video]) -> list[Video]:
    """Order videos newest first (stable for equal publication times)."""
    return sorted(videos, key=lambda video: video.published_at, reverse=True)
