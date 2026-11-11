"""Helpers that render the latest YouTube videos into the profile README.

Public API:

* :class:`~youtube_videos.models.Video` -- the video domain model.
* :func:`~youtube_videos.sources.fetch_videos` -- fetch from RSS or Data API.
* :func:`~youtube_videos.render.render_cards` -- render the card grid.
* :func:`~youtube_videos.readme.replace_block` -- inject the grid into a README.
* :func:`~youtube_videos.cli.main` -- the command line entry point.
"""

from __future__ import annotations

from .cli import DEFAULT_CHANNEL_ID, DEFAULT_COUNT, DEFAULT_README, build_parser, main
from .models import (
    MONTH_ABBREVIATIONS_ES,
    SHORT_MAX_DURATION_SECONDS,
    SHORT_UNAMBIGUOUS_MAX_SECONDS,
    Video,
    compact_number,
    format_date,
    format_duration,
    is_live_video,
    is_short_video,
    parse_iso8601_duration,
    sort_videos,
)
from .readme import (
    BEGIN_MARKER,
    END_MARKER,
    MarkersNotFound,
    detect_newline,
    extract_block,
    replace_block,
)
from .render import CELL_WIDTH, COLUMNS, escape_text, render_cards
from .sources import (
    API_BASE_URL,
    HTTP_TIMEOUT_SECONDS,
    RSS_CHANNEL_URL,
    RSS_PLAYLIST_URL,
    build_videos_from_api,
    fetch_videos,
    fetch_videos_from_api,
    fetch_videos_from_rss,
    filter_future_videos,
    filter_videos,
    parse_rss_feed,
    parse_video_details,
    post_process_videos,
    thumbnail_url_for,
    uploads_playlist_id,
)

__all__ = [
    "API_BASE_URL",
    "BEGIN_MARKER",
    "CELL_WIDTH",
    "COLUMNS",
    "DEFAULT_CHANNEL_ID",
    "DEFAULT_COUNT",
    "DEFAULT_README",
    "END_MARKER",
    "HTTP_TIMEOUT_SECONDS",
    "MONTH_ABBREVIATIONS_ES",
    "MarkersNotFound",
    "RSS_CHANNEL_URL",
    "RSS_PLAYLIST_URL",
    "SHORT_MAX_DURATION_SECONDS",
    "SHORT_UNAMBIGUOUS_MAX_SECONDS",
    "Video",
    "build_parser",
    "build_videos_from_api",
    "compact_number",
    "detect_newline",
    "escape_text",
    "extract_block",
    "fetch_videos",
    "fetch_videos_from_api",
    "fetch_videos_from_rss",
    "filter_future_videos",
    "filter_videos",
    "format_date",
    "format_duration",
    "is_live_video",
    "is_short_video",
    "main",
    "parse_iso8601_duration",
    "parse_rss_feed",
    "parse_video_details",
    "post_process_videos",
    "render_cards",
    "replace_block",
    "sort_videos",
    "thumbnail_url_for",
    "uploads_playlist_id",
]
