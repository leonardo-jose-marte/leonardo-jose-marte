"""Data sources for the YouTube video cards.

Two sources are supported and both return the same ``list[Video]``:

* the public **RSS feed** (no API key, no quota), used as the primary source;
* the optional **YouTube Data API v3**, used to enrich the videos with
  durations, view/like counts and better thumbnails, and to filter out
  Shorts and live broadcasts.

The API is strictly optional: any failure degrades gracefully to the RSS
feed. Secrets are read from the environment only, are sent exclusively in
the ``X-Goog-Api-Key`` request header, and are never written to a URL, a
log line or an exception message. Failures are reported by exception type
only, so nothing request related can leak into the logs.
"""

from __future__ import annotations

import json
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any, Mapping, Optional, Sequence

from .models import (
    Video,
    is_live_video,
    is_short_video,
    parse_iso8601_duration,
    sort_videos,
)

__all__ = [
    "HTTP_TIMEOUT_SECONDS",
    "API_BASE_URL",
    "RSS_CHANNEL_URL",
    "RSS_PLAYLIST_URL",
    "uploads_playlist_id",
    "thumbnail_url_for",
    "parse_rss_feed",
    "fetch_videos_from_rss",
    "parse_video_details",
    "build_videos_from_api",
    "filter_videos",
    "filter_future_videos",
    "post_process_videos",
    "fetch_videos_from_api",
    "fetch_videos",
]

#: Every outbound request uses the same generous timeout.
HTTP_TIMEOUT_SECONDS = 30

API_BASE_URL = "https://www.googleapis.com/youtube/v3"
RSS_CHANNEL_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={identifier}"
RSS_PLAYLIST_URL = "https://www.youtube.com/feeds/videos.xml?playlist_id={identifier}"

#: The uploads playlist of a channel is ``UU`` + the channel id without ``UC``.
UPLOADS_PLAYLIST_PREFIX = "UU"

#: XML namespaces used by the YouTube Atom feed.
NS_ATOM = "http://www.w3.org/2005/Atom"
NS_YT = "http://www.youtube.com/xml/schemas/2015"
NS_MEDIA = "http://search.yahoo.com/mrss/"

_USER_AGENT = "Mozilla/5.0 (compatible; youtube-readme-videos/1.0)"

#: Thumbnail preference when the Data API exposes ``snippet.thumbnails``.
THUMBNAIL_PREFERENCE = ("maxres", "medium", "high", "default")

#: ``videos.list`` accepts at most 50 ids per request.
MAX_VIDEO_IDS_PER_REQUEST = 50


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _warn(message: str) -> None:
    """Print a warning to stderr so stdout stays machine readable."""
    print(f"warning: {message}", file=sys.stderr)


def _local_name(tag: str) -> str:
    """Return the tag name without its XML namespace."""
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


def _element_text(
    element: ET.Element, local_name: str, namespace: Optional[str] = None
) -> str:
    """Return the text of a child element, preferring the given namespace."""
    if namespace:
        found = element.find(f"{{{namespace}}}{local_name}")
        if found is not None and found.text:
            return found.text.strip()
    for child in element:
        if _local_name(child.tag) == local_name and child.text:
            return child.text.strip()
    return ""


def _to_int(value: Any) -> Optional[int]:
    """Best effort conversion of an API value to ``int``."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_timestamp(value: Optional[str]) -> Optional[datetime]:
    """Parse an ISO 8601 timestamp into a timezone-aware UTC datetime."""
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def uploads_playlist_id(channel_id: str) -> str:
    """Return the uploads playlist id derived from a channel id."""
    if channel_id.startswith("UC") and len(channel_id) > 2:
        return UPLOADS_PLAYLIST_PREFIX + channel_id[2:]
    return UPLOADS_PLAYLIST_PREFIX + channel_id


def thumbnail_url_for(video_id: str) -> str:
    """Return the always-available 16:9 thumbnail for a video id."""
    return f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg"


def _fetch_bytes(url: str, headers: Optional[Mapping[str, str]] = None) -> bytes:
    """Perform a GET request and return the raw body."""
    request_headers = {"User-Agent": _USER_AGENT}
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(url, headers=request_headers)
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
        return response.read()


def _fetch_json(url: str, api_key: str) -> Any:
    """Perform a GET request against the Data API and decode the JSON body.

    The API key travels in the ``X-Goog-Api-Key`` header only; it is never
    appended to the query string.
    """
    headers = {"X-Goog-Api-Key": api_key, "Accept": "application/json"}
    payload = _fetch_bytes(url, headers)
    return json.loads(payload.decode("utf-8"))


def _candidate_count(count: int) -> int:
    """Return how many playlist items to request before filtering."""
    return max(count * 3, 15)


# --------------------------------------------------------------------------- #
# shared post-processing
# --------------------------------------------------------------------------- #
def filter_videos(videos: Sequence[Video]) -> list[Video]:
    """Drop live broadcasts and Shorts from a video list."""
    return [video for video in videos if not video.is_live and not video.is_short]


def filter_future_videos(
    videos: Sequence[Video], now: Optional[datetime] = None
) -> tuple[list[Video], int]:
    """Drop videos published after ``now``.

    Uploads playlists can list scheduled premieres and future dated
    uploads; the README only shows what is already public.

    Returns the kept videos and how many were dropped.
    """
    moment = now if now is not None else datetime.now(timezone.utc)
    kept = [video for video in videos if video.published_at <= moment]
    return kept, len(videos) - len(kept)


def post_process_videos(
    videos: Sequence[Video],
    count: int,
    now: Optional[datetime] = None,
) -> list[Video]:
    """Apply the shared post-processing to a list of videos.

    The order matters: future dated videos are dropped first, then live
    broadcasts and Shorts, and only the remaining videos are truncated to
    the requested count.
    """
    moment = now if now is not None else datetime.now(timezone.utc)
    kept, dropped = filter_future_videos(videos, moment)
    if dropped:
        _warn(
            f"Dropped {dropped} video(s) published after "
            f"{moment.strftime('%Y-%m-%d')}."
        )
    return filter_videos(kept)[:count]


# --------------------------------------------------------------------------- #
# RSS source
# --------------------------------------------------------------------------- #
def _entry_views(entry: ET.Element) -> Optional[int]:
    """Extract the view count from ``media:community/media:statistics``."""
    statistics = entry.find(f".//{{{NS_MEDIA}}}statistics")
    if statistics is None:
        for group in entry:
            if _local_name(group.tag) != "group":
                continue
            for community in group:
                if _local_name(community.tag) != "community":
                    continue
                for candidate in community:
                    if _local_name(candidate.tag) == "statistics":
                        statistics = candidate
                        break
    if statistics is None:
        return None
    return _to_int(statistics.get("views"))


def parse_rss_feed(
    xml_text: str, count: Optional[int] = None
) -> list[Video]:
    """Parse a YouTube Atom feed into videos ordered newest first.

    Element text is already unescaped by ``ElementTree``, so titles are used
    verbatim; the renderer escapes them again for HTML output.
    """
    root = ET.fromstring(xml_text)
    entries = [child for child in root if _local_name(child.tag) == "entry"]
    if not entries:
        entries = [node for node in root.iter() if _local_name(node.tag) == "entry"]
    videos: list[Video] = []
    for entry in entries:
        video_id = _element_text(entry, "videoId", NS_YT)
        published = _element_text(entry, "published", NS_ATOM)
        if not video_id or not published:
            continue
        published_at = parse_timestamp(published)
        if published_at is None:
            _warn("Skipping a feed entry with an unparsable publication date.")
            continue
        title = _element_text(entry, "title", NS_ATOM)
        videos.append(
            Video(
                video_id=video_id,
                title=title,
                published_at=published_at,
                thumbnail_url=thumbnail_url_for(video_id),
                view_count=_entry_views(entry),
            )
        )
    ordered = sort_videos(videos)
    if count is not None:
        return ordered[:count]
    return ordered


def fetch_videos_from_rss(
    channel_id: str, count: int, now: Optional[datetime] = None
) -> list[Video]:
    """Fetch the latest videos of a channel from its public RSS feed."""
    payload = _fetch_bytes(RSS_CHANNEL_URL.format(identifier=channel_id))
    videos = parse_rss_feed(payload.decode("utf-8"))
    if not videos:
        # Fall back to the uploads playlist feed, which exposes the same data.
        playlist_id = uploads_playlist_id(channel_id)
        payload = _fetch_bytes(RSS_PLAYLIST_URL.format(identifier=playlist_id))
        videos = parse_rss_feed(payload.decode("utf-8"))
    return post_process_videos(videos, count, now=now)


# --------------------------------------------------------------------------- #
# Data API source
# --------------------------------------------------------------------------- #
def _select_thumbnail(
    thumbnails: Mapping[str, Any], video_id: str
) -> str:
    """Pick the best available thumbnail, falling back to the CDN default."""
    for key in THUMBNAIL_PREFERENCE:
        entry = thumbnails.get(key)
        if isinstance(entry, Mapping) and entry.get("url"):
            return str(entry["url"])
    return thumbnail_url_for(video_id)


def _video_from_detail(
    item: Mapping[str, Any],
    fallback_title: Optional[str] = None,
    fallback_published_at: Optional[datetime] = None,
) -> Optional[Video]:
    """Build a video from a ``videos.list`` API item.

    The optional fallbacks carry the data that only the playlist response
    knows about, namely the playlist title and the publication date.
    """
    snippet = item.get("snippet") or {}
    video_id = str(snippet.get("videoId") or item.get("id") or "")
    if not video_id:
        return None
    published_at = parse_timestamp(snippet.get("publishedAt")) or fallback_published_at
    if published_at is None:
        return None

    content_details = item.get("contentDetails") or {}
    duration_seconds: Optional[int] = None
    raw_duration = content_details.get("duration")
    if raw_duration:
        try:
            duration_seconds = parse_iso8601_duration(str(raw_duration))
        except ValueError:
            duration_seconds = None

    statistics = item.get("statistics") or {}
    thumbnails = snippet.get("thumbnails") or {}
    title = snippet.get("title") or fallback_title or ""
    return Video(
        video_id=video_id,
        title=str(title),
        published_at=published_at,
        thumbnail_url=_select_thumbnail(thumbnails, video_id),
        duration_seconds=duration_seconds,
        view_count=_to_int(statistics.get("viewCount")),
        like_count=_to_int(statistics.get("likeCount")),
        is_short=is_short_video(duration_seconds, "shortsAspectRatio" in thumbnails),
        is_live=is_live_video(snippet.get("liveBroadcastContent")),
    )


def parse_video_details(items: Sequence[Mapping[str, Any]]) -> list[Video]:
    """Build videos from a ``videos.list`` API response.

    The response carries the real publication date, the duration, the
    statistics and the thumbnail set, so live broadcasts and Shorts can be
    detected here.
    """
    videos: list[Video] = []
    for item in items:
        video = _video_from_detail(item)
        if video is not None:
            videos.append(video)
    return sort_videos(videos)


def build_videos_from_api(
    playlist_items: Sequence[Mapping[str, Any]],
    detail_items: Sequence[Mapping[str, Any]],
) -> list[Video]:
    """Merge ``playlistItems`` with ``videos.list`` details into videos.

    The publication date comes from ``contentDetails.videoPublishedAt``
    (the moment the video was published) and never from
    ``snippet.publishedAt`` (the moment the item joined the playlist).
    """
    details_by_id = {
        str((item.get("snippet") or {}).get("videoId") or item.get("id") or ""): item
        for item in detail_items
    }
    videos: list[Video] = []
    for item in playlist_items:
        snippet = item.get("snippet") or {}
        resource_id = snippet.get("resourceId") or {}
        video_id = str(resource_id.get("videoId") or "")
        if not video_id:
            continue
        published_at = parse_timestamp(
            (item.get("contentDetails") or {}).get("videoPublishedAt")
        )
        detail = details_by_id.get(video_id)
        if detail is None:
            continue
        video = _video_from_detail(
            detail,
            fallback_title=str(snippet.get("title") or ""),
            fallback_published_at=published_at,
        )
        if video is None:
            continue
        videos.append(
            Video(
                video_id=video.video_id,
                title=str(snippet.get("title") or video.title),
                published_at=published_at or video.published_at,
                thumbnail_url=video.thumbnail_url,
                duration_seconds=video.duration_seconds,
                view_count=video.view_count,
                like_count=video.like_count,
                is_short=video.is_short,
                is_live=video.is_live,
            )
        )
    return sort_videos(videos)


def fetch_videos_from_api(
    channel_id: str,
    count: int,
    api_key: str,
    now: Optional[datetime] = None,
) -> list[Video]:
    """Fetch the latest videos of a channel through the Data API.

    More items than requested are pulled so the count survives the live and
    Shorts filtering.
    """
    channels = _fetch_json(
        f"{API_BASE_URL}/channels?part=contentDetails&id={channel_id}", api_key
    )
    items = channels.get("items") or []
    if not items:
        raise RuntimeError("The Data API returned no channel for the given id")
    uploads = (((items[0].get("contentDetails") or {}).get("relatedPlaylists") or {}).get("uploads"))
    if not uploads:
        raise RuntimeError("The Data API returned no uploads playlist for the channel")

    max_results = min(_candidate_count(count), MAX_VIDEO_IDS_PER_REQUEST)
    playlist = _fetch_json(
        f"{API_BASE_URL}/playlistItems?part=snippet,contentDetails"
        f"&playlistId={uploads}&maxResults={max_results}",
        api_key,
    )
    playlist_items = playlist.get("items") or []

    video_ids = []
    for item in playlist_items:
        video_id = ((item.get("snippet") or {}).get("resourceId") or {}).get("videoId")
        if video_id and video_id not in video_ids:
            video_ids.append(video_id)

    detail_items: list[Mapping[str, Any]] = []
    for start in range(0, len(video_ids), MAX_VIDEO_IDS_PER_REQUEST):
        chunk = video_ids[start : start + MAX_VIDEO_IDS_PER_REQUEST]
        if not chunk:
            continue
        videos = _fetch_json(
            f"{API_BASE_URL}/videos?part=contentDetails,statistics,snippet"
            f"&id={','.join(chunk)}",
            api_key,
        )
        detail_items.extend(videos.get("items") or [])

    built = build_videos_from_api(playlist_items, detail_items)
    return post_process_videos(built, count, now=now)


# --------------------------------------------------------------------------- #
# orchestration
# --------------------------------------------------------------------------- #
def fetch_videos(
    channel_id: str,
    count: int,
    api_key: Optional[str] = None,
    use_api: bool = True,
) -> tuple[list[Video], str, Optional[str]]:
    """Fetch videos from the best available source.

    Returns a ``(videos, source, api_error)`` tuple where ``source`` is
    ``"api"`` or ``"rss"`` and ``api_error`` is the exception type name of a
    failed Data API call (``None`` when the API was not used or worked).
    """
    api_error: Optional[str] = None
    # Evaluated once per run so every source compares against the same
    # instant.
    now = datetime.now(timezone.utc)

    if use_api and api_key:
        try:
            videos = fetch_videos_from_api(channel_id, count, api_key, now=now)
        except Exception as exc:  # type name only: nothing request related leaks
            api_error = type(exc).__name__
            _warn(
                "The YouTube Data API request failed "
                f"({api_error}); falling back to the RSS feed."
            )
        else:
            if videos:
                return videos, "api", None
            api_error = "NoVideosReturned"
            _warn(
                "The YouTube Data API returned no videos; falling back to the RSS feed."
            )
    elif use_api:
        _warn("No YOUTUBE_API_KEY found; using the RSS feed only.")
    else:
        _warn("The Data API was disabled; using the RSS feed only.")

    _warn(
        "Shorts filtering was skipped: the RSS feed carries no duration information."
    )
    videos = fetch_videos_from_rss(channel_id, count, now=now)
    return videos, "rss", api_error
