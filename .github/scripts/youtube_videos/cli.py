"""Command line interface that refreshes the YouTube cards in the README.

Usage::

    python .github/scripts/update_videos.py [options]

Options:
    --readme PATH       README to update (default: <repo root>/README.md)
    --channel-id ID     channel to read (default: $YOUTUBE_CHANNEL_ID)
    --count N           number of videos (default: $YOUTUBE_VIDEO_COUNT or 6)
    --no-api            use the RSS feed only
    --dry-run           print the rendered block, do not touch the README
    --check             exit 1 when the README is out of date
    --json              print a JSON summary instead of the rendered block

Exit codes: ``0`` success, ``1`` out of date (only with ``--check``),
``2`` error or bad usage.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional, Sequence

from .models import Video
from .readme import MarkersNotFound, replace_block
from .render import render_cards
from .sources import fetch_videos

__all__ = [
    "DEFAULT_CHANNEL_ID",
    "DEFAULT_COUNT",
    "DEFAULT_README",
    "REPO_ROOT",
    "build_parser",
    "main",
]

#: The script lives at ``<root>/.github/scripts/update_videos.py``; the helper
#: package lives one level deeper, so the repository root is three levels up.
PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parent.parent.parent
DEFAULT_README = REPO_ROOT / "README.md"

#: Channel of the profile README, used when no environment variable is set.
DEFAULT_CHANNEL_ID = "UCeJfqKpQiBVbrLBUvk-pMFg"

#: Number of videos rendered when nothing else is configured.
DEFAULT_COUNT = 6

EXIT_OK = 0
EXIT_OUT_OF_DATE = 1
EXIT_ERROR = 2


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    parser = argparse.ArgumentParser(
        prog="update_videos.py",
        description="Render the latest YouTube videos into the profile README.",
    )
    parser.add_argument(
        "--readme",
        type=Path,
        default=DEFAULT_README,
        help="README file to update (default: %(default)s)",
    )
    parser.add_argument(
        "--channel-id",
        default=None,
        help="YouTube channel id (default: $YOUTUBE_CHANNEL_ID)",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=None,
        help="number of videos to render (default: $YOUTUBE_VIDEO_COUNT or 6)",
    )
    parser.add_argument(
        "--no-api",
        action="store_true",
        help="skip the YouTube Data API and use the RSS feed only",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the rendered block without modifying the README",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 1 when the README does not hold the up to date block",
    )
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="print a JSON summary instead of the rendered block",
    )
    return parser


def _env_int(name: str, default: int) -> int:
    """Read an integer environment variable, falling back to ``default``."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        print(
            f"warning: {name} is not a valid integer; using {default}.",
            file=sys.stderr,
        )
        return default


def _read_text(path: Path) -> Optional[str]:
    """Read a text file preserving its line endings, or ``None`` on error."""
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return handle.read()
    except FileNotFoundError:
        return None
    except OSError as exc:
        print(f"error: cannot read {path} ({type(exc).__name__})", file=sys.stderr)
        return None


def _write_text(path: Path, text: str) -> None:
    """Write UTF-8 text without a BOM and without newline translation."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        handle.write(text.encode("utf-8"))


def _summary(
    channel_id: str,
    videos: Sequence[Video],
    source: str,
    changed: bool,
    api_error: Optional[str],
) -> dict[str, Any]:
    """Build the JSON summary object."""
    return {
        "channel_id": channel_id,
        "count": len(videos),
        "videos": [
            {
                "video_id": video.video_id,
                "title": video.title,
                "published_at": video.published_at.isoformat(),
                "duration_seconds": video.duration_seconds,
                "view_count": video.view_count,
                "like_count": video.like_count,
                "thumbnail_url": video.thumbnail_url,
            }
            for video in videos
        ],
        "source": source,
        "changed": changed,
        "api_error": api_error,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Entry point of the update script."""
    parser = build_parser()
    args = parser.parse_args(argv)

    channel_id = (
        args.channel_id
        or os.environ.get("YOUTUBE_CHANNEL_ID")
        or DEFAULT_CHANNEL_ID
    )
    count = args.count if args.count is not None else _env_int(
        "YOUTUBE_VIDEO_COUNT", DEFAULT_COUNT
    )
    if count <= 0:
        print("error: --count must be a positive integer.", file=sys.stderr)
        return EXIT_ERROR

    api_key = os.environ.get("YOUTUBE_API_KEY") or None
    try:
        videos, source, api_error = fetch_videos(
            channel_id,
            count,
            api_key=api_key,
            use_api=not args.no_api,
        )
    except Exception as exc:  # type name only: nothing request related leaks
        print(f"error: could not fetch videos ({type(exc).__name__})", file=sys.stderr)
        return EXIT_ERROR

    block = render_cards(videos)
    readme_path = Path(args.readme)
    current = _read_text(readme_path)

    new_text: Optional[str] = None
    changed = True
    if current is not None:
        try:
            new_text = replace_block(current, block)
        except MarkersNotFound as exc:
            print(f"error: {exc}", file=sys.stderr)
        else:
            changed = new_text != current

    summary = _summary(channel_id, videos, source, changed, api_error)

    if args.dry_run:
        if args.json_output:
            print(json.dumps(summary, ensure_ascii=False, indent=2))
        else:
            print(block)
        return EXIT_OK

    if new_text is None:
        print(
            f"error: {readme_path} does not contain the YouTube card markers.",
            file=sys.stderr,
        )
        return EXIT_ERROR

    if args.check:
        if args.json_output:
            print(json.dumps(summary, ensure_ascii=False, indent=2))
        return EXIT_OUT_OF_DATE if changed else EXIT_OK

    if changed:
        _write_text(readme_path, new_text)
        print(
            f"updated {readme_path}: {len(videos)} videos (source: {source}).",
            file=sys.stderr,
        )
    elif args.json_output:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(
            f"{readme_path} is already up to date ({len(videos)} videos, "
            f"source: {source}).",
            file=sys.stderr,
        )
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
