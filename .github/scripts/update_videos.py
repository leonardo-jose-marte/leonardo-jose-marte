#!/usr/bin/env python3
"""Refresh the YouTube video cards in the profile README.

Thin entry point: it makes ``.github/scripts`` importable so the
``youtube_videos`` package can be imported when the file is executed
directly by path, then hands over to the CLI.

Usage::

    python .github/scripts/update_videos.py [--dry-run] [--check] [--json]
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from youtube_videos.cli import main  # noqa: E402  (path setup must run first)

if __name__ == "__main__":
    sys.exit(main())
