"""A folder of page images (one chapter or volume) as CBZ pages."""
from pathlib import Path
from typing import List

from shutong.engine.kinds.base import BuildError

from .cbz import Page, _natural_key, image_extension

_SNIFF_BYTES = 32


def collect_folder_pages(folder: Path) -> List[Page]:
    """First-level image files in natural order; pages point at the original files."""
    pages = []
    for path in Path(folder).iterdir():
        if path.name.startswith(".") or path.is_symlink() or not path.is_file():
            continue
        try:
            with open(path, "rb") as handle:
                extension = image_extension(handle.read(_SNIFF_BYTES))
        except OSError as error:
            raise BuildError("page image could not be read: {0}".format(path.name)) from error
        if extension is not None:
            pages.append(Page(path.name, extension, path))
    if not pages:
        raise BuildError("folder contains no images: {0}".format(Path(folder).name))
    pages.sort(key=lambda page: _natural_key(page.name))
    return pages
