"""``series.json`` (Mylar's format) beside a series' CBZ files, for Komga.

Komga names a series after the ComicInfo ``Series`` plus `` (Volume)`` unless the volume is 1, so a manga
series shows up as "海贼王[Bilibili] (4)". It reads ``series.json`` after the books and lets it win: with
``volume`` 1 the name stays as it is, and the series gets the summary, status and publisher besides.
Kavita only reads archives and images, so the file is invisible there.

Everything is taken from the ComicInfo of the newest book in the folder, which is what Shutong wrote last.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import secrets
from typing import Dict, List, Optional
import zipfile

from .comicinfo import read_comic_info

SERIES_JSON = "series.json"
_SUBJECT = re.compile(r"/subject/(\d+)")


def write_series_json(folder: Path) -> bool:
    """Bring ``folder/series.json`` up to date with the books in it; True when the file was (re)written.

    A folder that holds no CBZ loses the file instead, so it does not keep an emptied folder alive.
    """
    folder = Path(folder)
    if not folder.is_dir():
        return False
    target = folder / SERIES_JSON
    books = _books(folder)
    if not books:
        if target.is_file():
            target.unlink()
        return False
    content = _content(folder, books)
    try:
        if target.read_bytes() == content:
            return False
    except OSError:
        pass
    staged = folder / ".{0}.{1}.tmp".format(SERIES_JSON, secrets.token_hex(4))
    try:
        staged.write_bytes(content)
        os.replace(staged, target)
    finally:
        if staged.exists():
            staged.unlink()
    return True


def _books(folder: Path) -> List[Path]:
    return [path for path in folder.iterdir()
            if path.suffix.lower() == ".cbz" and path.is_file() and not path.name.startswith(".")]


def _content(folder: Path, books: List[Path]) -> bytes:
    newest = max(books, key=lambda path: (path.stat().st_mtime_ns, path.name))
    info = _comic_info(newest)
    count = _integer(info.get("Count"))  # only written for a finished series
    subject = _SUBJECT.search(info.get("Web", ""))
    metadata = {
        "type": "comicSeries",
        "publisher": info.get("Publisher", ""),
        "imprint": None,
        "name": info.get("Series") or folder.name,
        "comicid": subject.group(1) if subject else "",
        "year": _integer(info.get("Year")) or 0,
        "description_text": info.get("Summary") or None,
        "description_formatted": None,
        "volume": 1,
        "booktype": "Print",
        "age_rating": None,
        "comic_image": "",
        "total_issues": count or len(books),
        "publication_run": "",
        "status": "Ended" if count else "Continuing",
    }
    return json.dumps({"version": "1.0.2", "metadata": metadata}, ensure_ascii=False, indent=2).encode("utf-8")


def _comic_info(path: Path) -> Dict[str, str]:
    try:
        return read_comic_info(path)
    except (KeyError, OSError, zipfile.BadZipFile, ValueError, SyntaxError):  # no or unreadable ComicInfo.xml
        return {}


def _integer(value: Optional[str]) -> Optional[int]:
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None
