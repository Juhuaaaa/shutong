"""Covers inside organized files: which image a reader shows first, and cropping a dust jacket to its front.

Media servers take a CBZ's first page, so a chosen cover goes in front as page ``000`` (no existing page is
touched); archives whose pages are not numbered get ``!cover`` instead, the name Kavita prefers over the first
page. Only manga have this: a light novel keeps the cover its EPUB came with.

Scanned editions often start with the unfolded jacket (flaps, front, spine, back) as one wide image. The front of
a right-to-left book sits immediately left of the spine, which is searched for in the middle of a full jacket or
at the right end of a ``flap | front | spine`` half-jacket; the front's width follows the inner pages' shape.
"""
from dataclasses import dataclass
import io
import os
from pathlib import Path
import re
import secrets
import statistics
from typing import Dict, List, Optional, Tuple
import zipfile

import numpy as np
from PIL import Image

ANALYSIS_HEIGHT = 400
MIN_JACKET_ASPECT = 1.05
MAX_JACKET_ASPECT = 3.0  # wider strips are obi bands, not jackets
JPEG_QUALITY = 92
_IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif")
_NUMBERED_PAGE = re.compile(r"^[0-9]{3,}\.[a-z]+$")
_ADDED_COVER = re.compile(r"^(?:0+|!cover)\.[a-z]+$")
_PAGE_COUNT = re.compile(rb"<PageCount>(\d+)</PageCount>")
_COPY_CHUNK = 1024 * 1024


@dataclass(frozen=True)
class Jacket:
    page: str
    left: float  # the front, as fractions of the image's width
    right: float


@dataclass(frozen=True)
class CoverOptions:
    pages: Tuple[str, ...]  # the file's own images, in reading order
    current: Optional[str]  # the one that is the cover; None: an added or cropped cover
    added: bool = False
    jacket: Optional[Jacket] = None


def _natural_key(name: str) -> List[object]:
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", name.lower())]


def _is_added(name: str) -> bool:
    return bool(_ADDED_COVER.fullmatch(name))


def _archive_pages(archive: zipfile.ZipFile) -> List[str]:
    return sorted((name for name in archive.namelist() if name.lower().endswith(_IMAGE_SUFFIXES) and not _is_added(name)),
                  key=_natural_key)


def _added_name(archive: zipfile.ZipFile) -> Optional[str]:
    return next((name for name in archive.namelist() if _is_added(name)), None)


# ---- reading -------------------------------------------------------------------------------------------------


def cover_options(path: Path) -> CoverOptions:
    with zipfile.ZipFile(path) as archive:
        pages = _archive_pages(archive)
        added = _added_name(archive) is not None
    return CoverOptions(tuple(pages), None if added else (pages[0] if pages else None), added, find_jacket(path))


def read_page(path: Path, page: str) -> bytes:
    with zipfile.ZipFile(path) as archive:
        if page not in _archive_pages(archive):
            raise ValueError("这个文件里没有这一页：{0}".format(page))
        return archive.read(page)


def read_cover(path: Path) -> bytes:
    with zipfile.ZipFile(path) as archive:
        pages = _archive_pages(archive)
        name = _added_name(archive) or (pages[0] if pages else None)
        if name is None:
            raise ValueError("这个文件里没有图片")
        return archive.read(name)


def thumbnail(data: bytes, width: int) -> bytes:
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.draft("RGB", (width * 2, width * 4))
            image.thumbnail((width, width * 8))
            buffer = io.BytesIO()
            image.convert("RGB").save(buffer, format="JPEG", quality=80)
            return buffer.getvalue()
    except (OSError, Image.DecompressionBombError, SyntaxError) as error:
        raise ValueError("读不了这张图片：{0}".format(error)) from None


# ---- finding the front of a jacket -----------------------------------------------------------------------------


def _load(archive: zipfile.ZipFile, name: str) -> Image.Image:
    image = Image.open(io.BytesIO(archive.read(name)))
    image.load()
    return image


def _edge_profile(image: Image.Image) -> Tuple[np.ndarray, float]:
    """Per-column fold strength: a fold or panel border is a line through most rows, hence a low percentile."""
    scale = ANALYSIS_HEIGHT / image.height
    small = image.convert("RGB").resize((max(8, round(image.width * scale)), ANALYSIS_HEIGHT), Image.BILINEAR)
    pixels = np.asarray(small, dtype=np.float32)
    top, bottom = int(pixels.shape[0] * 0.05), int(pixels.shape[0] * 0.95)
    profiles = []
    for channel in range(3):
        values = pixels[top:bottom, :, channel]
        profiles.append(np.percentile(np.abs(values[:, 4:] - values[:, :-4]), 35, axis=0))
    edges = np.zeros(pixels.shape[1])
    edges[2:-2] = np.max(profiles, axis=0)
    # Image borders stand in for a missing flap or back panel.
    border = float(np.percentile(edges, 90))
    edges[0] = edges[-1] = max(edges[0], border)
    return edges, scale


def _locate_front(image: Image.Image, page_ratio: float) -> Optional[Tuple[int, int]]:
    edges, scale = _edge_profile(image)
    width, height = len(edges), ANALYSIS_HEIGHT
    front_low, front_high = int(page_ratio * 0.95 * height), int(page_ratio * 1.12 * height)
    spine_low, spine_high = int(0.025 * height), int(0.16 * height)
    if width / height >= 1.6:
        candidates = range(width // 2 - spine_high, width // 2 + spine_low)
    else:
        candidates = range(width - spine_high - 1, width - spine_low // 2)
    best = None
    for spine_left in candidates:
        if spine_left < front_low or spine_left >= width:
            continue
        start = max(0, spine_left - front_high)
        left = start + int(np.argmax(edges[start: spine_left - front_low + 1]))
        tail = edges[spine_left + spine_low: spine_left + spine_high + 1]
        spine_right = min(width - 1, spine_left + spine_low + int(np.argmax(tail))) if len(tail) else width - 1
        score = edges[spine_left] + edges[spine_right] + edges[left]
        if best is None or score > best[0]:
            best = (score, left, spine_left)
    return (int(best[1] / scale), int(best[2] / scale)) if best is not None else None


def _page_ratio(archive: zipfile.ZipFile, names: List[str]) -> float:
    """Median single-page shape from the middle of the volume."""
    ratios = []
    middle = len(names) // 2
    for name in names[middle: middle + 5]:
        with Image.open(io.BytesIO(archive.read(name))) as page:
            ratio = page.width / page.height
        ratios.append(ratio if ratio < 1 else ratio / 2)
    return statistics.median(ratios) if ratios else 0.66


def find_jacket(path: Path) -> Optional[Jacket]:
    """The front panel if the first page is a whole jacket; None for anything else, or when in doubt."""
    try:
        with zipfile.ZipFile(path) as archive:
            names = _archive_pages(archive)
            if len(names) < 2:
                return None
            image = _load(archive, names[0])
            if not MIN_JACKET_ASPECT < image.width / image.height <= MAX_JACKET_ASPECT:
                return None
            box = _locate_front(image, _page_ratio(archive, names[1:] or names))
    except (OSError, ValueError, SyntaxError, zipfile.BadZipFile, Image.DecompressionBombError):
        return None
    if box is None or box[1] - box[0] < image.height * 0.4:
        return None
    return Jacket(names[0], box[0] / image.width, box[1] / image.width)


def crop_image(data: bytes, left: float, right: float) -> bytes:
    if not 0 <= left < right <= 1:
        raise ValueError("裁剪范围不对")
    with Image.open(io.BytesIO(data)) as image:
        box = (round(left * image.width), 0, round(right * image.width), image.height)
        if box[2] - box[0] < 8:
            raise ValueError("裁剪范围太窄了")
        buffer = io.BytesIO()
        image.convert("RGB").crop(box).save(buffer, format="JPEG", quality=JPEG_QUALITY, optimize=True)
        return buffer.getvalue()


# ---- writing -----------------------------------------------------------------------------------------------------


def _staging(path: Path) -> Path:
    return path.with_name(".{0}.{1}.tmp".format(path.name, secrets.token_hex(4)))


def _extension(data: bytes) -> str:
    with Image.open(io.BytesIO(data)) as image:
        found = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp", "GIF": ".gif", "AVIF": ".avif"}.get(image.format or "")
    if found is None:
        raise ValueError("这张图片的格式不能当封面")
    return found


def _signature(archive: zipfile.ZipFile) -> Dict[str, Tuple[int, int]]:
    return {info.filename: (info.file_size, info.CRC) for info in archive.infolist()
            if info.filename != "ComicInfo.xml" and not _is_added(info.filename)}


def _rewrite_archive(path: Path, cover: Optional[bytes]) -> None:
    """Put ``cover`` in front (``None`` takes the added one out); every page is copied and checked, then swapped in."""
    staged = _staging(path)
    try:
        with zipfile.ZipFile(path) as source, zipfile.ZipFile(staged, "x", allowZip64=True) as output:
            old = _added_name(source)
            pages = [name for name in source.namelist() if name != "ComicInfo.xml" and not _is_added(name)]
            numbered = bool(pages) and all(_NUMBERED_PAGE.fullmatch(name) for name in pages)
            name = None
            if cover is not None:
                digits = max((len(page.split(".")[0]) for page in pages), default=3) if numbered else 0
                name = ("0" * digits if numbered else "!cover") + _extension(cover)
                info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
                info.external_attr = 0o644 << 16
                output.writestr(info, cover)
            change = (cover is not None) - (old is not None)
            for info in source.infolist():
                if _is_added(info.filename):
                    continue
                if info.filename == "ComicInfo.xml":
                    payload = _PAGE_COUNT.sub(lambda match: b"<PageCount>%d</PageCount>" % (int(match.group(1)) + change),
                                              source.read(info))
                    output.writestr(info, payload)
                    continue
                with source.open(info) as reader, output.open(info, "w") as writer:
                    while True:
                        chunk = reader.read(_COPY_CHUNK)
                        if not chunk:
                            break
                        writer.write(chunk)
            expected = _signature(source)
        with zipfile.ZipFile(staged) as check:
            if check.testzip() is not None or _signature(check) != expected:
                raise ValueError("写封面时页面有变化，已放弃")
            if name is not None and check.read(name) != cover:
                raise ValueError("写封面时封面有变化，已放弃")
        os.replace(staged, path)
    finally:
        if staged.exists():
            staged.unlink()


def set_cover(path: Path, page: str, left: Optional[float] = None, right: Optional[float] = None) -> None:
    """Make ``page`` the cover, cropped to ``left``..``right`` if given. The first page uncropped restores the file."""
    path = Path(path)
    data = read_page(path, page)
    if left is not None or right is not None:
        _rewrite_archive(path, crop_image(data, 0.0 if left is None else left, 1.0 if right is None else right))
        return
    with zipfile.ZipFile(path) as archive:
        first = _archive_pages(archive)[0]
    _rewrite_archive(path, None if page == first else data)
