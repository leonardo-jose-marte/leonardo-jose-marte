"""Unit tests for the YouTube video card helpers.

No test touches the network: the RSS parser is fed inline Atom XML and the
CLI is driven with a stubbed data source.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

import pytest

from youtube_videos import cli
from youtube_videos.models import (
    Video,
    compact_number,
    format_date,
    format_duration,
    is_live_video,
    is_short_video,
    parse_iso8601_duration,
    sort_videos,
)
from youtube_videos.readme import (
    BEGIN_MARKER,
    END_MARKER,
    MarkersNotFound,
    detect_newline,
    extract_block,
    replace_block,
)
from youtube_videos.render import escape_text, render_cards
from youtube_videos.sources import (
    build_videos_from_api,
    filter_future_videos,
    filter_videos,
    parse_rss_feed,
    parse_video_details,
    post_process_videos,
    thumbnail_url_for,
    uploads_playlist_id,
)

UTC = timezone.utc


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015"
      xmlns:media="http://search.yahoo.com/mrss/"
      xmlns="http://www.w3.org/2005/Atom">
  <title>DataCode</title>
  <entry>
    <id>yt:video:aaaaaaaaaaa</id>
    <yt:videoId>aaaaaaaaaaa</yt:videoId>
    <yt:channelId>UCeJfqKpQiBVbrLBUvk-pMFg</yt:channelId>
    <title>Curso de Go &amp; Rust</title>
    <link rel="alternate" href="https://www.youtube.com/watch?v=aaaaaaaaaaa"/>
    <published>2026-11-10T18:00:07+00:00</published>
    <updated>2026-11-11T12:01:02+00:00</updated>
    <media:group>
      <media:title>Curso de Go &amp; Rust</media:title>
      <media:thumbnail url="https://i2.ytimg.com/vi/aaaaaaaaaaa/hqdefault.jpg" width="480" height="360"/>
      <media:community>
        <media:starRating count="1094" average="5.00" min="1" max="5"/>
        <media:statistics views="52673"/>
      </media:community>
    </media:group>
  </entry>
  <entry>
    <id>yt:video:bbbbbbbbbbb</id>
    <yt:videoId>bbbbbbbbbbb</yt:videoId>
    <yt:channelId>UCeJfqKpQiBVbrLBUvk-pMFg</yt:channelId>
    <title>Introducción a Python: métodos #1</title>
    <link rel="alternate" href="https://www.youtube.com/watch?v=bbbbbbbbbbb"/>
    <published>2026-11-08T09:30:00+00:00</published>
    <updated>2026-11-08T09:30:00+00:00</updated>
    <media:group>
      <media:title>Introducción a Python: métodos #1</media:title>
      <media:thumbnail url="https://i2.ytimg.com/vi/bbbbbbbbbbb/hqdefault.jpg" width="480" height="360"/>
      <media:community>
        <media:starRating count="12" average="5.00" min="1" max="5"/>
        <media:statistics views="1200"/>
      </media:community>
    </media:group>
  </entry>
  <entry>
    <id>yt:video:ccccccccccc</id>
    <yt:videoId>ccccccccccc</yt:videoId>
    <yt:channelId>UCeJfqKpQiBVbrLBUvk-pMFg</yt:channelId>
    <title>Configuración de Git &amp; GitHub</title>
    <link rel="alternate" href="https://www.youtube.com/watch?v=ccccccccccc"/>
    <published>2026-11-05T12:00:00+00:00</published>
    <updated>2026-11-05T12:00:00+00:00</updated>
    <media:group>
      <media:title>Configuración de Git &amp; GitHub</media:title>
      <media:thumbnail url="https://i2.ytimg.com/vi/ccccccccccc/hqdefault.jpg" width="480" height="360"/>
      <media:community>
        <media:starRating count="3" average="5.00" min="1" max="5"/>
        <media:statistics views="999"/>
      </media:community>
    </media:group>
  </entry>
</feed>
"""


def make_video(
    video_id: str = "abcdefghijk",
    title: str = "Un video",
    published_at: datetime = datetime(2026, 11, 10, 18, 0, 7, tzinfo=UTC),
    **kwargs,
) -> Video:
    """Build a video for the rendering tests."""
    defaults = {
        "thumbnail_url": thumbnail_url_for(video_id),
        "duration_seconds": 1116,
        "view_count": 1234,
    }
    defaults.update(kwargs)
    return Video(
        video_id=video_id,
        title=title,
        published_at=published_at,
        **defaults,
    )


# --------------------------------------------------------------------------- #
# 1. duration parsing
# --------------------------------------------------------------------------- #
def test_parse_iso8601_duration():
    assert parse_iso8601_duration("PT1M5S") == 65
    assert parse_iso8601_duration("PT1H6M56S") == 4016
    assert parse_iso8601_duration("P1DT2H") == 93600
    assert parse_iso8601_duration("PT0S") == 0


def test_parse_iso8601_duration_rejects_invalid_values():
    for invalid in ("", "not-a-duration", "1M5S", "PT", "P", "PT1X"):
        with pytest.raises(ValueError):
            parse_iso8601_duration(invalid)


# --------------------------------------------------------------------------- #
# 2. compact numbers
# --------------------------------------------------------------------------- #
def test_compact_number():
    assert compact_number(999) == "999"
    assert compact_number(1000) == "1K"
    assert compact_number(1234) == "1.2K"
    assert compact_number(9999) == "10K"
    assert compact_number(1500000) == "1.5M"
    assert compact_number(2000) == "2K"
    assert compact_number(2000000) == "2M"
    assert compact_number(1000000000) == "1B"


# --------------------------------------------------------------------------- #
# 3. duration formatting
# --------------------------------------------------------------------------- #
def test_format_duration():
    assert format_duration(65) == "1:05"
    assert format_duration(4016) == "1:06:56"
    assert format_duration(0) == "0:00"
    assert format_duration(59) == "0:59"
    assert format_duration(3600) == "1:00:00"


# --------------------------------------------------------------------------- #
# 4. date formatting
# --------------------------------------------------------------------------- #
def test_format_date():
    assert format_date(datetime(2026, 11, 10, 18, 0, 7, tzinfo=UTC)) == "10 nov 2026"
    assert format_date(datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)) == "1 ene 2026"
    assert format_date(datetime(2026, 12, 31, 23, 59, 0, tzinfo=UTC)) == "31 dic 2026"


# --------------------------------------------------------------------------- #
# 5. RSS parsing
# --------------------------------------------------------------------------- #
def test_parse_rss_feed_returns_unwrapped_titles_and_metadata():
    videos = parse_rss_feed(RSS_XML)

    assert len(videos) == 3
    assert [video.video_id for video in videos] == [
        "aaaaaaaaaaa",
        "bbbbbbbbbbb",
        "ccccccccccc",
    ]

    # ElementTree already unescaped the entities: the titles must not be
    # double escaped.
    assert videos[0].title == "Curso de Go & Rust"
    assert "&amp;" not in videos[0].title
    assert videos[1].title == "Introducción a Python: métodos #1"
    assert videos[2].title == "Configuración de Git & GitHub"

    assert videos[0].published_at == datetime(2026, 11, 10, 18, 0, 7, tzinfo=UTC)
    assert videos[1].published_at == datetime(2026, 11, 8, 9, 30, 0, tzinfo=UTC)
    assert videos[0].published_at.tzinfo is not None

    assert videos[0].thumbnail_url == "https://i.ytimg.com/vi/aaaaaaaaaaa/mqdefault.jpg"
    assert videos[2].thumbnail_url == "https://i.ytimg.com/vi/ccccccccccc/mqdefault.jpg"

    assert [video.view_count for video in videos] == [52673, 1200, 999]
    assert all(video.duration_seconds is None for video in videos)


def test_parse_rss_feed_honours_the_requested_count():
    assert len(parse_rss_feed(RSS_XML, count=2)) == 2


def test_uploads_playlist_id_is_derived_from_the_channel_id():
    assert uploads_playlist_id("UCeJfqKpQiBVbrLBUvk-pMFg") == "UUeJfqKpQiBVbrLBUvk-pMFg"


# --------------------------------------------------------------------------- #
# 6. shorts detection
# --------------------------------------------------------------------------- #
def test_is_short_video():
    # Very short upload without an aspect ratio hint: still a Short.
    assert is_short_video(45, has_shorts_aspect_ratio=False) is True
    # Shorts between 61 and 180 seconds only count with the hint.
    assert is_short_video(120, has_shorts_aspect_ratio=True) is True
    assert is_short_video(120, has_shorts_aspect_ratio=False) is False
    # Anything above three minutes is a regular video.
    assert is_short_video(200, has_shorts_aspect_ratio=False) is False
    assert is_short_video(200, has_shorts_aspect_ratio=True) is False
    # Unknown duration: nothing can be concluded.
    assert is_short_video(None, has_shorts_aspect_ratio=True) is False


def test_api_details_mark_shorts_and_live_broadcasts():
    items = [
        {
            "id": "shortvid1",
            "snippet": {
                "videoId": "shortvid1",
                "title": "Short",
                "publishedAt": "2026-11-10T18:00:07+00:00",
                "liveBroadcastContent": "none",
                "thumbnails": {"default": {"url": "https://example.test/d.jpg"}},
            },
            "contentDetails": {"duration": "PT45S"},
            "statistics": {"viewCount": "10"},
        },
        {
            "id": "shortvid2",
            "snippet": {
                "videoId": "shortvid2",
                "title": "Short con thumbnail vertical",
                "publishedAt": "2026-11-09T18:00:07+00:00",
                "liveBroadcastContent": "none",
                "thumbnails": {
                    "default": {"url": "https://example.test/d.jpg"},
                    "shortsAspectRatio": {"url": "https://example.test/s.jpg"},
                },
            },
            "contentDetails": {"duration": "PT2M"},
            "statistics": {"viewCount": "20"},
        },
        {
            "id": "regular001",
            "snippet": {
                "videoId": "regular001",
                "title": "Video normal",
                "publishedAt": "2026-11-08T18:00:07+00:00",
                "liveBroadcastContent": "none",
                "thumbnails": {"default": {"url": "https://example.test/d.jpg"}},
            },
            "contentDetails": {"duration": "PT2M"},
            "statistics": {"viewCount": "30"},
        },
        {
            "id": "livevid001",
            "snippet": {
                "videoId": "livevid001",
                "title": "Directo",
                "publishedAt": "2026-11-07T18:00:07+00:00",
                "liveBroadcastContent": "live",
                "thumbnails": {"default": {"url": "https://example.test/d.jpg"}},
            },
            "contentDetails": {"duration": "PT1H"},
            "statistics": {"viewCount": "40"},
        },
    ]

    videos = parse_video_details(items)
    by_id = {video.video_id: video for video in videos}

    assert by_id["shortvid1"].is_short is True
    assert by_id["shortvid2"].is_short is True
    assert by_id["regular001"].is_short is False
    assert by_id["livevid001"].is_live is True

    kept = filter_videos(videos)
    assert [video.video_id for video in kept] == ["regular001"]


# --------------------------------------------------------------------------- #
# 7. live detection
# --------------------------------------------------------------------------- #
def test_is_live_video():
    assert is_live_video("live") is True
    assert is_live_video("upcoming") is True
    assert is_live_video("none") is False
    assert is_live_video(None) is False


# --------------------------------------------------------------------------- #
# 8. rendering
# --------------------------------------------------------------------------- #
def test_render_cards_builds_a_three_by_two_grid():
    videos = [make_video(video_id=f"video{index}") for index in range(6)]
    markup = render_cards(videos)

    assert markup.count("<table>") == 1
    assert markup.count("<tr>") == 2
    assert markup.count("<td ") == 6
    assert markup.count("<img ") == 6
    # One distinct video link per card; each card renders it twice, once
    # around the thumbnail and once around the title.
    links = re.findall(r'href="https://youtu\.be/([^"]+)"', markup)
    assert len(set(links)) == 6
    assert len(links) == 12
    assert markup.count("youtu.be/") == 12


def test_render_cards_escapes_untrusted_values():
    videos = [make_video(title='<script>alert("x")</script> & más')]
    markup = render_cards(videos)

    assert "<script>" not in markup
    assert "&lt;script&gt;" in markup
    assert "&amp;" in markup
    assert "&quot;" in markup
    assert escape_text('<script>alert("x")</script> & más') in markup


def test_render_cards_keeps_the_grid_with_fewer_videos():
    videos = [make_video(video_id=f"video{index}") for index in range(4)]
    markup = render_cards(videos)

    # Four videos fill one full row of three plus a remainder cell.
    assert markup.count("<tr>") == 2
    assert markup.count("<td ") == 4
    assert markup.count("<img ") == 4


def test_render_cards_fills_the_remainder_row():
    videos = [make_video(video_id=f"video{index}") for index in range(5)]
    markup = render_cards(videos)

    # Five videos fill one full row of three plus a remainder row of two.
    assert markup.count("<tr>") == 2
    assert markup.count("<td ") == 5
    assert markup.count("<img ") == 5


def test_render_cards_uses_three_columns_and_the_thirty_three_percent_width():
    videos = [make_video(video_id=f"video{index}") for index in range(6)]
    markup = render_cards(videos)

    assert markup.count('<td width="33%" valign="top">') == 6
    assert 'width="50%"' not in markup


def test_render_cards_metadata_line_omits_unknown_parts():
    videos = [
        make_video(
            video_id="withmeta",
            view_count=1234,
            duration_seconds=1116,
        ),
        make_video(
            video_id="noviews",
            published_at=datetime(2026, 11, 10, 18, 0, 7, tzinfo=UTC),
            view_count=None,
            duration_seconds=None,
        ),
    ]
    markup = render_cards(videos)

    assert "1.2K visualizaciones · 18:36 · 10 nov 2026" in markup
    assert "<sub>10 nov 2026</sub>" in markup


def test_render_cards_shows_the_view_count():
    """The card displays how many views the video has.

    The counter is live, so the block changes between runs; the workflow
    runs weekly precisely to refresh it.
    """
    markup = render_cards([make_video(video_id="withviews", view_count=1234)])

    assert "1.2K visualizaciones" in markup


# --------------------------------------------------------------------------- #
# 9-11. readme block handling
# --------------------------------------------------------------------------- #
def test_replace_block_only_touches_the_inner_content():
    readme = (
        "# Titulo\n\n"
        f"{BEGIN_MARKER}\n"
        "contenido viejo\n"
        f"{END_MARKER}\n\n"
        "Seccion final\n"
    )

    updated = replace_block(readme, "<table>\n  <tr></tr>\n</table>")

    assert updated.startswith("# Titulo\n\n" + BEGIN_MARKER)
    assert updated.endswith(END_MARKER + "\n\nSeccion final\n")
    assert "contenido viejo" not in updated
    assert "<table>" in updated
    assert updated.count(BEGIN_MARKER) == 1
    assert updated.count(END_MARKER) == 1


def test_replace_block_requires_both_markers():
    with pytest.raises(MarkersNotFound):
        replace_block("sin marcadores\n", "<table></table>")
    with pytest.raises(MarkersNotFound):
        replace_block(f"{BEGIN_MARKER}\nsolo inicio\n", "<table></table>")
    with pytest.raises(MarkersNotFound):
        replace_block(f"solo final\n{END_MARKER}\n", "<table></table>")


def test_replace_block_is_idempotent():
    readme = f"antes\n{BEGIN_MARKER}\nviejo\n{END_MARKER}\ndespues\n"
    block = "<table>\n  <tr>\n    <td>x</td>\n  </tr>\n</table>"

    once = replace_block(readme, block)
    twice = replace_block(once, block)

    assert once == twice


def test_replace_block_preserves_the_crlf_line_ending_style():
    readme = f"antes\r\n{BEGIN_MARKER}\r\nviejo\r\n{END_MARKER}\r\ndespues\r\n"

    updated = replace_block(readme, "<table>\n  <tr>\n    <td>x</td>\n  </tr>\n</table>")

    assert "\r\n" in updated
    assert "\n" not in updated.replace("\r\n", "")
    assert detect_newline(updated) == "\r\n"


def test_extract_block_returns_the_inner_content():
    readme = f"antes\n{BEGIN_MARKER}\ncontenido\n{END_MARKER}\ndespues\n"

    assert extract_block(readme) == "\ncontenido\n"
    assert extract_block("sin marcadores") is None


# --------------------------------------------------------------------------- #
# 12. sorting
# --------------------------------------------------------------------------- #
def test_videos_are_sorted_newest_first():
    base = datetime(2026, 11, 10, 18, 0, 7, tzinfo=UTC)
    older = make_video(video_id="older", published_at=base - timedelta(days=2))
    newest = make_video(video_id="newest", published_at=base)
    middle = make_video(video_id="middle", published_at=base - timedelta(days=1))

    assert [video.video_id for video in sort_videos([older, newest, middle])] == [
        "newest",
        "middle",
        "older",
    ]
    # The feed parser applies the same ordering.
    assert [
        video.video_id
        for video in parse_rss_feed(
            RSS_XML.replace("2026-11-10T18:00:07+00:00", "2020-01-01T00:00:00+00:00")
        )
    ] == ["bbbbbbbbbbb", "ccccccccccc", "aaaaaaaaaaa"]


# --------------------------------------------------------------------------- #
# 13. future dated videos
# --------------------------------------------------------------------------- #
def test_filter_future_videos_drops_scheduled_uploads():
    now = datetime(2026, 11, 10, 18, 0, 7, tzinfo=UTC)
    published = make_video(video_id="published", published_at=now - timedelta(days=1))
    scheduled = make_video(video_id="scheduled", published_at=now + timedelta(days=2))
    also_published = make_video(
        video_id="also", published_at=now - timedelta(hours=1)
    )

    kept, dropped = filter_future_videos([published, scheduled, also_published], now=now)

    assert [video.video_id for video in kept] == ["published", "also"]
    assert dropped == 1


def test_post_process_videos_filters_future_shorts_and_live():
    now = datetime(2026, 11, 10, 18, 0, 7, tzinfo=UTC)
    regular = make_video(video_id="regular", published_at=now - timedelta(days=1))
    scheduled = make_video(video_id="scheduled", published_at=now + timedelta(days=1))
    short = make_video(
        video_id="short",
        published_at=now - timedelta(days=1),
        duration_seconds=30,
        is_short=True,
    )
    live = make_video(
        video_id="live",
        published_at=now - timedelta(days=1),
        duration_seconds=3600,
        is_live=True,
    )

    kept = post_process_videos([regular, scheduled, short, live], count=10, now=now)

    assert [video.video_id for video in kept] == ["regular"]


def test_post_process_videos_truncates_after_filtering():
    now = datetime(2026, 11, 10, 18, 0, 7, tzinfo=UTC)
    videos = [
        make_video(
            video_id=f"video{index}",
            published_at=now - timedelta(days=index + 1),
        )
        for index in range(6)
    ]

    assert len(post_process_videos(videos, count=3, now=now)) == 3


# --------------------------------------------------------------------------- #
# 14. api merge
# --------------------------------------------------------------------------- #
def test_build_videos_from_api_uses_the_real_publication_date():
    playlist_items = [
        {
            "snippet": {
                "title": "Titulo del playlist",
                "publishedAt": "2026-11-11T12:00:00+00:00",
                "resourceId": {"videoId": "aaaaaaaaaaa"},
            },
            "contentDetails": {"videoPublishedAt": "2026-11-10T18:00:07+00:00"},
        }
    ]
    detail_items = [
        {
            "id": "aaaaaaaaaaa",
            "snippet": {
                "videoId": "aaaaaaaaaaa",
                "title": "Titulo real",
                "publishedAt": "2026-11-10T18:00:07+00:00",
                "liveBroadcastContent": "none",
                "thumbnails": {
                    "maxres": {"url": "https://i.ytimg.com/vi/aaaaaaaaaaa/maxres.jpg"},
                    "medium": {"url": "https://i.ytimg.com/vi/aaaaaaaaaaa/mq.jpg"},
                },
            },
            "contentDetails": {"duration": "PT1H6M56S"},
            "statistics": {"viewCount": "52673", "likeCount": "1094"},
        }
    ]

    videos = build_videos_from_api(playlist_items, detail_items)

    assert len(videos) == 1
    video = videos[0]
    assert video.published_at == datetime(2026, 11, 10, 18, 0, 7, tzinfo=UTC)
    assert video.duration_seconds == 4016
    assert video.view_count == 52673
    assert video.like_count == 1094
    assert video.thumbnail_url == "https://i.ytimg.com/vi/aaaaaaaaaaa/maxres.jpg"


# --------------------------------------------------------------------------- #
# 14. command line interface
# --------------------------------------------------------------------------- #
def test_cli_dry_run_prints_the_block_without_touching_the_readme(tmp_path, monkeypatch):
    readme = tmp_path / "README.md"
    original = f"# Perfil\n\n{BEGIN_MARKER}\nviejo\n{END_MARKER}\n"
    readme.write_text(original, encoding="utf-8")

    monkeypatch.setattr(cli, "fetch_videos", lambda *a, **k: (_stub_videos(), "rss", None))

    exit_code = cli.main(["--readme", str(readme), "--dry-run"])

    assert exit_code == 0
    assert readme.read_text(encoding="utf-8") == original


def test_cli_json_summary_shape(tmp_path, monkeypatch, capsys):
    readme = tmp_path / "README.md"
    readme.write_text(f"{BEGIN_MARKER}\nviejo\n{END_MARKER}\n", encoding="utf-8")

    monkeypatch.setattr(cli, "fetch_videos", lambda *a, **k: (_stub_videos(), "rss", None))

    exit_code = cli.main(["--readme", str(readme), "--dry-run", "--json"])

    assert exit_code == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["count"] == 2
    assert summary["source"] == "rss"
    assert summary["api_error"] is None
    assert summary["changed"] is True
    assert summary["videos"][0]["video_id"] == "abcdefghijk"
    assert set(summary["videos"][0]) == {
        "video_id",
        "title",
        "published_at",
        "duration_seconds",
        "view_count",
        "like_count",
        "thumbnail_url",
    }


def test_cli_check_reports_out_of_date_and_up_to_date(tmp_path, monkeypatch):
    readme = tmp_path / "README.md"
    readme.write_text(f"{BEGIN_MARKER}\nviejo\n{END_MARKER}\n", encoding="utf-8")

    monkeypatch.setattr(cli, "fetch_videos", lambda *a, **k: (_stub_videos(), "rss", None))

    assert cli.main(["--readme", str(readme), "--check"]) == 1

    cli.main(["--readme", str(readme)])
    assert cli.main(["--readme", str(readme), "--check"]) == 0


def test_cli_writes_the_block_and_stays_idempotent(tmp_path, monkeypatch):
    readme = tmp_path / "README.md"
    readme.write_text(
        f"# Perfil\n\n{BEGIN_MARKER}\nviejo\n{END_MARKER}\n\nfin\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(cli, "fetch_videos", lambda *a, **k: (_stub_videos(), "rss", None))

    assert cli.main(["--readme", str(readme)]) == 0
    first = readme.read_bytes()
    assert b"<table>" in first
    assert "viejo" not in first.decode("utf-8")

    assert cli.main(["--readme", str(readme)]) == 0
    assert readme.read_bytes() == first


def _stub_videos() -> list[Video]:
    return [
        make_video(video_id="abcdefghijk", title="Primero"),
        make_video(
            video_id="zyxwvutsrq",
            title="Segundo",
            published_at=datetime(2026, 11, 9, 12, 0, 0, tzinfo=UTC),
        ),
    ]


# --------------------------------------------------------------------------- #
# weekly rollover
# --------------------------------------------------------------------------- #
def build_feed(entries: list[tuple[str, str, str]]) -> str:
    """Build an Atom feed with the given (video_id, published, title) triples."""
    body = "\n".join(
        f"""  <entry>
    <id>yt:video:{video_id}</id>
    <yt:videoId>{video_id}</yt:videoId>
    <yt:channelId>UCeJfqKpQiBVbrLBUvk-pMFg</yt:channelId>
    <title>{title}</title>
    <link rel="alternate" href="https://www.youtube.com/watch?v={video_id}"/>
    <published>{published}</published>
    <updated>{published}</updated>
    <media:group>
      <media:title>{title}</media:title>
      <media:thumbnail url="https://i2.ytimg.com/vi/{video_id}/hqdefault.jpg" width="480" height="360"/>
      <media:community>
        <media:starRating count="10" average="5.00" min="1" max="5"/>
        <media:statistics views="100"/>
      </media:community>
    </media:group>
  </entry>"""
        for video_id, published, title in entries
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015"\n'
        '      xmlns:media="http://search.yahoo.com/mrss/"\n'
        '      xmlns="http://www.w3.org/2005/Atom">\n'
        "  <title>DataCode</title>\n"
        f"{body}\n"
        "</feed>\n"
    )


def test_a_new_upload_pushes_the_oldest_video_out_of_the_grid():
    """The grid always shows the six newest uploads and rolls over.

    This is the weekly behaviour of the README: the feed is fetched fresh
    on every run, sorted newest first and cut to six, so a new upload
    becomes the first card and the video that was sixth disappears.
    """
    week_one = [
        ("aaaaaaaaaaa", "2026-11-10T18:00:07+00:00", "Video A"),
        ("bbbbbbbbbbb", "2026-11-09T18:00:07+00:00", "Video B"),
        ("ccccccccccc", "2026-11-08T18:00:07+00:00", "Video C"),
        ("ddddddddddd", "2026-11-07T18:00:07+00:00", "Video D"),
        ("eeeeeeeeeee", "2026-11-06T18:00:07+00:00", "Video E"),
        ("fffffffffff", "2026-11-05T18:00:07+00:00", "Video F"),
        ("ggggggggggg", "2026-11-04T18:00:07+00:00", "Video G"),
    ]

    first = render_cards(parse_rss_feed(build_feed(week_one), 6))

    assert first.index("aaaaaaaaaaa") < first.index("bbbbbbbbbbb")
    assert "ffffffffff" in first  # the sixth video is still on the grid
    assert "ggggggggggg" not in first  # the seventh never made it in
    assert first.count("<td ") == 6

    # The next week a new video is published.
    week_two = [("zzzzzzzzzzz", "2026-11-11T18:00:07+00:00", "Video Z")] + week_one

    second = render_cards(parse_rss_feed(build_feed(week_two), 6))

    assert "zzzzzzzzzzz" in second  # the new upload is on the grid
    assert second.index("zzzzzzzzzzz") < second.index("aaaaaaaaaaa")
    assert "ffffffffff" not in second  # the oldest one fell out
    assert "eeeeeeeeeee" in second  # the fifth moved down but stayed
    assert second.count("<td ") == 6
    assert second.count("<tr>") == 2
