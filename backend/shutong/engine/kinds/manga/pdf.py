"""Turn a scanned-manga PDF into CBZ pages.

Ported from the legacy convert_pdf_series.py: each page is dominated by one embedded
image, copied out at full resolution. Bilevel and greyscale scans are stored as PNG,
colour as JPEG; pages without an image become a blank page of the volume's usual size.
"""
from collections import Counter
import io
from pathlib import Path
from typing import List, Optional, Tuple

from PIL import Image
from pypdf import PdfReader

from shutong.engine.kinds.base import BuildError

from .cbz import Page


def pdf_page_count(source: Path) -> int:
    """Pages of a readable, unencrypted PDF; BuildError otherwise."""
    count = len(_read_pages(source))
    if count == 0:
        raise BuildError("PDF has no pages")
    return count


def _read_pages(source: Path) -> list:
    try:
        reader = PdfReader(str(source))
        # Owner-password-only PDFs (common for scans) report is_encrypted but open with "".
        if reader.is_encrypted and not reader.decrypt(""):
            raise BuildError("PDF is encrypted")
        return list(reader.pages)
    except BuildError:
        raise
    except Exception as error:  # pypdf raises KeyError/TypeError/... on damaged files
        raise BuildError("PDF could not be read: {0}".format(error)) from error


def collect_pdf_pages(source: Path, workdir: Path) -> List[Page]:
    pdf_pages = _read_pages(source)

    # Write each page as soon as it is encoded: a scanned volume can be gigabytes.
    pages: List[Optional[Page]] = []
    sizes: Counter = Counter()
    try:
        for number, pdf_page in enumerate(pdf_pages, start=1):
            image = _largest_image(pdf_page)
            if image is None:
                pages.append(None)
                continue
            sizes[image.size] += 1
            data, extension = _encode(image)
            pages.append(_write_page(workdir, number, data, extension))
        if not sizes:
            raise BuildError("PDF has no embedded page images")
        fallback = sizes.most_common(1)[0][0]
        for index, page in enumerate(pages):
            if page is None:
                data, extension = _blank_page(fallback)
                pages[index] = _write_page(workdir, index + 1, data, extension)
    except BuildError:
        raise
    except Exception as error:
        raise BuildError("PDF page could not be converted: {0}".format(error)) from error
    return pages


def _write_page(workdir: Path, number: int, data: bytes, extension: str) -> Page:
    name = "{0:05d}{1}".format(number, extension)
    path = Path(workdir) / ("pdf-" + name)
    path.write_bytes(data)
    return Page(name, extension, path)


def _largest_image(page) -> Optional[Image.Image]:
    best = None
    try:
        images = list(page.images)
    except Exception:
        return None
    for item in images:
        try:
            image = Image.open(io.BytesIO(item.data))
            image.load()
        except Exception:
            continue
        if best is None or image.size[0] * image.size[1] > best.size[0] * best.size[1]:
            best = image
    return best


def _encode(image: Image.Image) -> Tuple[bytes, str]:
    buffer = io.BytesIO()
    if image.mode in ("1", "L"):
        # Bilevel and greyscale scans are both lossless and compact as PNG.
        image.save(buffer, format="PNG", optimize=True)
        return buffer.getvalue(), ".png"
    if image.mode != "RGB":
        image = image.convert("RGB")
    image.save(buffer, format="JPEG", quality=92)
    return buffer.getvalue(), ".jpg"


def _blank_page(size: Tuple[int, int]) -> Tuple[bytes, str]:
    buffer = io.BytesIO()
    Image.new("1", size, 1).save(buffer, format="PNG", optimize=True)
    return buffer.getvalue(), ".png"
