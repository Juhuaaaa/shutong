"""EPUB OPF metadata reading and Kavita-compatible rewriting.

Kavita reads series grouping information from the OPF package document:

* EPUB 2: ``<meta name="calibre:series" content="..."/>`` plus
  ``<meta name="calibre:series_index" content="..."/>``
* EPUB 3: ``<meta property="belongs-to-collection" ...>Series</meta>`` plus a
  refined ``group-position`` item.

Specials are recognised by Kavita from the ``SP\\d+`` marker in the filename
and are placed in the reserved volume ``100000``; the series metadata still has
to point at the owning series.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
import posixpath
import re
from typing import Optional, Tuple
from urllib.parse import unquote, urlsplit
import zipfile
from xml.etree import ElementTree as ET

OPF_NAMESPACE = "http://www.idpf.org/2007/opf"
DC_NAMESPACE = "http://purl.org/dc/elements/1.1/"
CONTAINER_NAMESPACE = "urn:oasis:names:tc:opendocument:xmlns:container"

OPF = "{%s}" % OPF_NAMESPACE
DC = "{%s}" % DC_NAMESPACE
CONTAINER = "{%s}" % CONTAINER_NAMESPACE

SPECIAL_VOLUME_INDEX = 100000
SERIES_COLLECTION_ID = "kavita-series"
WEB_IDENTIFIER_ID = "kavita-bgm-url"

ET.register_namespace("opf", OPF_NAMESPACE)
ET.register_namespace("dc", DC_NAMESPACE)


@dataclass(frozen=True)
class EpubMetadata:
    """The subset of OPF metadata used for discovery and verification."""

    title: str
    creators: Tuple[str, ...]
    languages: Tuple[str, ...]
    description: str
    publisher: str
    subjects: Tuple[str, ...]
    date: str
    series: Optional[str]
    series_index: Optional[str]
    version: str


@dataclass(frozen=True)
class KavitaMetadata:
    """Metadata to write so that Kavita groups one EPUB into a series."""

    series: str
    series_index: Decimal
    title: str
    language: str = "zh"
    authors: Tuple[str, ...] = ()
    publisher: str = ""
    illustrators: Tuple[str, ...] = ()
    genres: Tuple[str, ...] = ()
    description: str = ""
    date: str = ""
    web_url: str = ""


def find_package_document(archive: zipfile.ZipFile) -> str:
    """Return the OPF member name declared by ``META-INF/container.xml``."""
    names = set(archive.namelist())
    container_name = "META-INF/container.xml"
    if container_name in names:
        try:
            container = ET.fromstring(archive.read(container_name))
        except ET.ParseError:
            container = None
        if container is not None:
            for rootfile in container.iter(CONTAINER + "rootfile"):
                full_path = (_attr(rootfile, "full-path") or "").strip()
                if full_path and full_path in names:
                    return full_path
    candidates = sorted(name for name in names if name.lower().endswith(".opf"))
    if not candidates:
        raise ValueError("EPUB has no OPF package document")
    return candidates[0]


def read_metadata(path: Path) -> EpubMetadata:
    """Read series/volume metadata from an EPUB without modifying it."""
    path = Path(path)
    with zipfile.ZipFile(path) as archive:
        package_name = find_package_document(archive)
        package = ET.fromstring(archive.read(package_name))
    return _metadata_from_package(package)


def write_metadata(source: Path, destination: Path, metadata: KavitaMetadata) -> None:
    """Copy ``source`` to ``destination`` and rewrite only its OPF metadata."""
    source = Path(source)
    destination = Path(destination)
    if source.resolve() == destination.resolve():
        raise ValueError("source and destination EPUB must be different files")
    if not metadata.series:
        raise ValueError("series must be a non-empty string")
    if Decimal(metadata.series_index) < 0:
        raise ValueError("series_index must not be negative")
    if not metadata.title.strip():
        raise ValueError("title must be a non-empty string")

    with zipfile.ZipFile(source) as archive:
        names = set(archive.namelist())
        package_name = find_package_document(archive)
        package = ET.fromstring(_read_member(archive, archive.getinfo(package_name)))
        _apply_metadata(package, metadata, names, package_name)
        spine_paths = _spine_paths(package, package_name)
        rewritten = {
            package_name: _serialize_default_namespace(package, OPF_NAMESPACE)
        }
        for name in sorted(names):
            if not name.lower().endswith(".ncx"):
                continue
            sanitized = _sanitize_ncx(
                _read_member(archive, archive.getinfo(name)),
                member_name=name,
                member_names=names,
                spine_paths=spine_paths,
            )
            if sanitized is not None:
                rewritten[name] = sanitized
        manifest = package.find(OPF + "manifest")
        nav_names = []
        if manifest is not None:
            for item in manifest.findall(OPF + "item"):
                if "nav" not in (_attr(item, "properties") or "").split():
                    continue
                resolved = _resolve_href(
                    package_name, _attr(item, "href") or ""
                )
                if resolved in names:
                    nav_names.append(resolved)
        for name in sorted(set(nav_names)):
            sanitized = _sanitize_nav_document(
                _read_member(archive, archive.getinfo(name)),
                member_name=name,
                member_names=names,
                spine_paths=spine_paths,
            )
            if sanitized is not None:
                rewritten[name] = sanitized
        with zipfile.ZipFile(destination, "w") as output:
            _write_mimetype(archive, output)
            written = set()
            for info in archive.infolist():
                if info.filename == "mimetype":
                    continue
                if info.filename in written:
                    continue
                data = rewritten.get(info.filename)
                if data is None:
                    data = _read_member(archive, info)
                output.writestr(_copy_info(info), data)
                written.add(info.filename)


def _metadata_from_package(package: ET.Element) -> EpubMetadata:
    metadata = package.find(OPF + "metadata")
    if metadata is None:
        raise ValueError("EPUB OPF has no metadata element")
    version = (_attr(package, "version") or "2.0").strip() or "2.0"

    def texts(tag: str) -> Tuple[str, ...]:
        values = []
        for element in metadata.findall(DC + tag):
            text = (element.text or "").strip()
            if text:
                values.append(text)
        return tuple(values)

    series = None
    series_index = None
    for item in metadata.findall(OPF + "meta"):
        name = (_attr(item, "name") or "").strip()
        prop = (_attr(item, "property") or "").strip()
        if name == "calibre:series":
            series = (_attr(item, "content") or "").strip() or series
        elif name == "calibre:series_index":
            series_index = (_attr(item, "content") or "").strip() or series_index
        elif prop == "belongs-to-collection":
            series = (item.text or "").strip() or series
        elif prop == "group-position":
            series_index = (item.text or "").strip() or series_index

    titles = metadata.findall(DC + "title")
    primary_title = ""
    if titles:
        primary_title = (_main_title_element(metadata, titles).text or "").strip()

    return EpubMetadata(
        title=primary_title,
        creators=texts("creator"),
        languages=texts("language"),
        description=(texts("description") or ("",))[0],
        publisher=(texts("publisher") or ("",))[0],
        subjects=texts("subject"),
        date=(texts("date") or ("",))[0],
        series=series,
        series_index=series_index,
        version=version,
    )


def _apply_metadata(
    package: ET.Element,
    metadata: KavitaMetadata,
    member_names: set,
    package_name: str,
) -> None:
    metadata_element = package.find(OPF + "metadata")
    if metadata_element is None:
        metadata_element = ET.Element(OPF + "metadata")
        package.insert(0, metadata_element)
    version = (_attr(package, "version") or "2.0").strip() or "2.0"
    major = _major_version(version)

    _set_title(metadata_element, metadata.title)
    _set_language(metadata_element, metadata.language)
    _set_people(metadata_element, metadata.authors, metadata.illustrators, major)
    if metadata.publisher:
        _set_single_text(metadata_element, "publisher", metadata.publisher)
    if metadata.description:
        _set_single_text(metadata_element, "description", metadata.description)
    if metadata.genres:
        _set_subjects(metadata_element, metadata.genres)
    if metadata.date:
        _set_date(metadata_element, metadata.date)
    if metadata.web_url:
        _set_web_identifier(metadata_element, metadata.web_url, major)
    _set_series_metadata(
        metadata_element, metadata.series, metadata.series_index, major
    )
    _sanitize_manifest(package)
    _sanitize_cover_metadata(package, member_names, package_name, major)
    _sanitize_spine(package, member_names, package_name)
    _sanitize_guide(package, member_names, package_name)


def _major_version(version: str) -> int:
    try:
        return int(version.split(".")[0])
    except (TypeError, ValueError):
        return 2


def _set_title(metadata_element: ET.Element, title: str) -> None:
    titles = metadata_element.findall(DC + "title")
    if not titles:
        element = ET.SubElement(metadata_element, DC + "title")
        element.text = title
        return
    main = _main_title_element(metadata_element, titles)
    main.text = title


def _main_title_element(
    metadata_element: ET.Element, titles: list
) -> ET.Element:
    main_ids = set()
    for item in metadata_element.findall(OPF + "meta"):
        if (_attr(item, "property") or "").strip() != "title-type":
            continue
        if (item.text or "").strip() != "main":
            continue
        refines = (_attr(item, "refines") or "").strip()
        if refines.startswith("#"):
            main_ids.add(refines[1:])
    for title in titles:
        if (_attr(title, "id") or "").strip() in main_ids:
            return title
    return titles[0]


def _set_language(metadata_element: ET.Element, language: str) -> None:
    for element in metadata_element.findall(DC + "language"):
        metadata_element.remove(element)
    element = ET.SubElement(metadata_element, DC + "language")
    element.text = language


# Roles the source speaks for: these people are replaced when it names the authors. A translator or
# an editor the file lists stays.
_REPLACED_ROLES = frozenset({"", "aut", "author", "creator", "cre", "ill", "illustrator", "art", "artist"})


def _set_people(
    metadata_element: ET.Element,
    authors: Tuple[str, ...],
    illustrators: Tuple[str, ...],
    major: int,
) -> None:
    """Write the source's authors and illustrators, each marked with its role.

    Kavita takes a role only from a ``marc:relators`` refinement, in EPUB 2 files as well, and counts every
    creator without one as a writer; EPUB 2's own ``opf:role`` is written too, for other readers.
    Without authors from the source the file's own creators stay.
    """
    authors = _clean_names(authors)
    illustrators = _clean_names(illustrators)
    metas = metadata_element.findall(OPF + "meta")
    roles = {}
    for item in metas:
        if (_attr(item, "property") or "").strip() == "role":
            refines = (_attr(item, "refines") or "").strip()
            if refines.startswith("#"):
                roles[refines[1:]] = (item.text or _attr(item, "content") or "").strip().lower()

    def role_of(creator: ET.Element) -> str:
        identifier = (_attr(creator, "id") or "").strip()
        if identifier in roles:
            return roles[identifier]
        return (_attr(creator, "role") or "").strip().lower()

    creators = metadata_element.findall(DC + "creator")
    if authors:
        for creator in creators:
            if role_of(creator) not in _REPLACED_ROLES:
                continue
            identifier = (_attr(creator, "id") or "").strip()
            if identifier:
                for item in metas:
                    if (_attr(item, "refines") or "").strip() == "#" + identifier:
                        metadata_element.remove(item)
            metadata_element.remove(creator)
        creators = metadata_element.findall(DC + "creator")
    else:
        named = {(creator.text or "").strip() for creator in creators}
        illustrators = tuple(name for name in illustrators if name not in named)

    used = {(_attr(item, "id") or "").strip() for item in metadata_element.iter()} - {""}

    def new_id() -> str:
        number = 1
        while "shutong-creator-%d" % number in used:
            number += 1
        used.add("shutong-creator-%d" % number)
        return "shutong-creator-%d" % number

    def mark(creator: ET.Element, role: str) -> None:
        identifier = (_attr(creator, "id") or "").strip()
        if not identifier:
            identifier = new_id()
            creator.set("id", identifier)
        refinement = ET.SubElement(metadata_element, OPF + "meta")
        refinement.set("refines", "#" + identifier)
        refinement.set("property", "role")
        refinement.set("scheme", "marc:relators")
        refinement.text = role

    # A role the file gives only as opf:role is one Kavita would not see.
    for creator in creators:
        identifier = (_attr(creator, "id") or "").strip()
        attribute = (_attr(creator, "role") or "").strip()
        if attribute and identifier not in roles:
            mark(creator, attribute)
        if major >= 3 and OPF + "role" in creator.attrib:
            del creator.attrib[OPF + "role"]

    for names, role in ((authors, "aut"), (illustrators, "ill")):
        for name in names:
            creator = ET.SubElement(metadata_element, DC + "creator")
            creator.text = name
            if major < 3:
                creator.set(OPF + "role", role)
            mark(creator, role)


def _clean_names(names: Tuple[str, ...]) -> Tuple[str, ...]:
    cleaned = []
    for name in names:
        name = (name or "").strip()
        if name and name not in cleaned:
            cleaned.append(name)
    return tuple(cleaned)


def _set_single_text(metadata_element: ET.Element, tag: str, value: str) -> None:
    elements = metadata_element.findall(DC + tag)
    if elements:
        elements[0].text = value
        for extra in elements[1:]:
            metadata_element.remove(extra)
    else:
        element = ET.SubElement(metadata_element, DC + tag)
        element.text = value


def _set_subjects(metadata_element: ET.Element, genres: Tuple[str, ...]) -> None:
    for element in metadata_element.findall(DC + "subject"):
        metadata_element.remove(element)
    for genre in genres:
        genre = genre.strip()
        if not genre:
            continue
        element = ET.SubElement(metadata_element, DC + "subject")
        element.text = genre


def _set_date(metadata_element: ET.Element, date: str) -> None:
    event_attribute = "{%s}event" % OPF_NAMESPACE
    elements = metadata_element.findall(DC + "date")
    if elements:
        elements[0].text = date
        for element in elements:
            if element.get(event_attribute) is not None:
                element.set(event_attribute, "publication")
        for extra in elements[1:]:
            metadata_element.remove(extra)
    else:
        element = ET.SubElement(metadata_element, DC + "date")
        element.text = date


def _set_web_identifier(
    metadata_element: ET.Element, web_url: str, major: int
) -> None:
    for element in metadata_element.findall(DC + "identifier"):
        text = (element.text or "").strip()
        if text == web_url or text == "url:" + web_url:
            return
    element = ET.SubElement(metadata_element, DC + "identifier")
    element.set("id", WEB_IDENTIFIER_ID)
    if major >= 3:
        element.text = "url:" + web_url
    else:
        element.set("{%s}scheme" % OPF_NAMESPACE, "URL")
        element.text = web_url


def _sanitize_manifest(package: ET.Element) -> None:
    """Drop duplicate manifest ids/hrefs that strict EPUB readers reject.

    Fan-made Chinese EPUBs frequently list the same CSS or font file twice.
    Kavita uses VersOne.Epub, which refuses such packages outright, so the
    duplicate entries are removed and any references are repointed.
    """
    manifest = package.find(OPF + "manifest")
    if manifest is None:
        return
    metadata = package.find(OPF + "metadata")
    spine = package.find(OPF + "spine")
    cover_id = ""
    if metadata is not None:
        for item in metadata.findall(OPF + "meta"):
            if (_attr(item, "name") or "").strip() == "cover":
                cover_id = (_attr(item, "content") or "").strip()
    spine_idrefs = []
    if spine is not None:
        spine_idrefs = [
            (_attr(ref, "idref") or "").strip()
            for ref in spine.findall(OPF + "itemref")
        ]

    seen_ids = set()
    unique_items = []
    for item in list(manifest.findall(OPF + "item")):
        item_id = (_attr(item, "id") or "").strip()
        if item_id and item_id in seen_ids:
            manifest.remove(item)
            continue
        if item_id:
            seen_ids.add(item_id)
        unique_items.append(item)

    kept = []
    replacement = {}
    for item in unique_items:
        href = (_attr(item, "href") or "").strip()
        member = _member_path(href)
        duplicate_of = None
        for existing in kept:
            existing_href = (_attr(existing, "href") or "").strip()
            if href and href == existing_href:
                duplicate_of = existing
                break
            if member and member == _member_path(existing_href):
                duplicate_of = existing
                break
        if duplicate_of is None:
            kept.append(item)
            continue
        keeper = _prefer_manifest_item(
            duplicate_of, item, spine_idrefs, cover_id
        )
        removed_item = item if keeper is duplicate_of else duplicate_of
        if keeper is item:
            kept[kept.index(duplicate_of)] = item
        manifest.remove(removed_item)
        removed_id = (_attr(removed_item, "id") or "").strip()
        kept_id = (_attr(keeper, "id") or "").strip()
        if removed_id and kept_id and removed_id != kept_id:
            replacement[removed_id] = kept_id

    if replacement and spine is not None:
        seen = set()
        for ref in list(spine.findall(OPF + "itemref")):
            idref = (_attr(ref, "idref") or "").strip()
            new_idref = replacement.get(idref, idref)
            if new_idref != idref:
                ref.set("idref", new_idref)
            if new_idref in seen:
                spine.remove(ref)
            else:
                seen.add(new_idref)
    if replacement and metadata is not None:
        for item in metadata.findall(OPF + "meta"):
            if (_attr(item, "name") or "").strip() != "cover":
                continue
            content = (_attr(item, "content") or "").strip()
            if content in replacement:
                item.set("content", replacement[content])


def _prefer_manifest_item(
    existing: ET.Element,
    candidate: ET.Element,
    spine_idrefs: list,
    cover_id: str,
) -> ET.Element:
    def score(item: ET.Element) -> int:
        item_id = (_attr(item, "id") or "").strip()
        value = 2 if item_id in spine_idrefs else 0
        if item_id and item_id == cover_id:
            value += 1
        return value

    return candidate if score(candidate) > score(existing) else existing


def _member_path(href: str) -> str:
    """Normalize a manifest href into a comparable member path."""
    if not href:
        return ""
    parsed = urlsplit(href)
    if parsed.scheme or parsed.netloc:
        return ""
    path = unquote(parsed.path).lstrip("/")
    if not path:
        return ""
    return posixpath.normpath(path)


def manifest_problems(package: ET.Element) -> Tuple[str, ...]:
    """Return reasons a strict EPUB reader would reject the manifest."""
    manifest = package.find(OPF + "manifest")
    if manifest is None:
        return ("EPUB OPF has no manifest element",)
    problems = []
    seen_ids = set()
    seen_paths = set()
    for item in manifest.findall(OPF + "item"):
        item_id = (_attr(item, "id") or "").strip()
        href = (_attr(item, "href") or "").strip()
        media_type = (_attr(item, "media-type") or "").strip()
        if not item_id:
            problems.append("manifest item is missing its id")
        elif item_id in seen_ids:
            problems.append("manifest item id {0!r} is not unique".format(item_id))
        else:
            seen_ids.add(item_id)
        if not href:
            problems.append("manifest item is missing its href")
        elif not media_type:
            problems.append("manifest item {0!r} is missing its media-type".format(item_id))
        else:
            key = _member_path(href) or href
            if key in seen_paths:
                problems.append(
                    "manifest href {0!r} is not unique".format(href)
                )
            else:
                seen_paths.add(key)
    spine = package.find(OPF + "spine")
    if spine is not None:
        for ref in spine.findall(OPF + "itemref"):
            idref = (_attr(ref, "idref") or "").strip()
            if idref and idref not in seen_ids:
                problems.append(
                    "spine references missing manifest id {0!r}".format(idref)
                )
    return tuple(problems)


def validate_package(path: Path) -> Tuple[str, ...]:
    """Open an EPUB and report defects that make strict readers reject it."""
    path = Path(path)
    problems = []
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        package_name = find_package_document(archive)
        package = ET.fromstring(archive.read(package_name))
        problems.extend(manifest_problems(package))
        problems.extend(_package_reference_problems(package, names, package_name))
        problems.extend(_link_problems(package, names, package_name, archive))
        for member in sorted(names):
            if member.lower().endswith(".ncx"):
                problems.extend(_ncx_problems(archive.read(member)))
        manifest = package.find(OPF + "manifest")
        if manifest is not None:
            for item in manifest.findall(OPF + "item"):
                properties = (_attr(item, "properties") or "").split()
                if "nav" not in properties:
                    continue
                resolved = _resolve_href(package_name, _attr(item, "href") or "")
                if resolved in names:
                    problems.extend(
                        _nav_document_problems(archive.read(resolved))
                    )
    return tuple(problems)


def _package_reference_problems(
    package: ET.Element, names: set, package_name: str
) -> Tuple[str, ...]:
    problems = []
    manifest = package.find(OPF + "manifest")
    metadata = package.find(OPF + "metadata")
    spine = package.find(OPF + "spine")
    items = manifest.findall(OPF + "item") if manifest is not None else []
    by_id = {(_attr(item, "id") or "").strip(): item for item in items}
    for item in items:
        if "cover-image" in (_attr(item, "properties") or "").split():
            href = _attr(item, "href") or ""
            if _resolve_href(package_name, href) not in names:
                problems.append(
                    "EPUB 3 cover image {0!r} is missing".format(href)
                )
    if metadata is not None:
        for item in metadata.findall(OPF + "meta"):
            if (_attr(item, "name") or "").strip() != "cover":
                continue
            cover_id = (_attr(item, "content") or "").strip()
            if not cover_id:
                problems.append("EPUB 2 cover metadata is missing its item id")
                continue
            cover_item = by_id.get(cover_id)
            if cover_item is None:
                problems.append(
                    "EPUB 2 cover metadata references missing id {0!r}".format(
                        cover_id
                    )
                )
            elif _resolve_href(package_name, _attr(cover_item, "href") or "") not in names:
                problems.append(
                    "EPUB 2 cover image {0!r} is missing".format(
                        _attr(cover_item, "href")
                    )
                )
    if spine is not None:
        for ref in spine.findall(OPF + "itemref"):
            idref = (_attr(ref, "idref") or "").strip()
            item = by_id.get(idref) if idref else None
            if item is None:
                continue
            if _resolve_href(package_name, _attr(item, "href") or "") not in names:
                problems.append(
                    "spine references missing file {0!r}".format(
                        _attr(item, "href")
                    )
                )
    return tuple(problems)


def _attr(element: ET.Element, name: str):
    """Case-insensitive attribute lookup (malformed EPUBs use ``Name``)."""
    target = name.lower()
    for key, value in element.attrib.items():
        local = key.rsplit("}", 1)[-1]
        if local.lower() == target:
            return value
    return None


def _link_problems(
    package: ET.Element,
    names: set,
    package_name: str,
    archive: zipfile.ZipFile,
) -> Tuple[str, ...]:
    """Report TOC/guide links that point outside the reading order (spine)."""
    problems = []
    spine_paths = _spine_paths(package, package_name)
    manifest = package.find(OPF + "manifest")

    def check(base: str, href: str, label: str) -> None:
        if not href or href.strip().startswith("#"):
            problems.append("{0} link {1!r} has no document target".format(label, href))
            return
        target = _resolve_href(base, href)
        if not target or target not in names or target not in spine_paths:
            problems.append(
                "{0} link {1!r} does not identify a spine section".format(
                    label, href
                )
            )

    for member in sorted(names):
        if member.lower().endswith(".ncx"):
            try:
                root = ET.fromstring(archive.read(member))
            except ET.ParseError:
                continue
            for element in root.iter():
                if _local_name(element.tag) == "content":
                    check(member, _attr(element, "src") or "", "NCX")

    if manifest is not None:
        for item in manifest.findall(OPF + "item"):
            if "nav" not in (_attr(item, "properties") or "").split():
                continue
            nav_path = _resolve_href(package_name, _attr(item, "href") or "")
            if nav_path not in names:
                continue
            try:
                root = ET.fromstring(archive.read(nav_path))
            except ET.ParseError:
                continue
            for element in root.iter():
                if _local_name(element.tag) == "a":
                    check(nav_path, _attr(element, "href") or "", "NAV")

    guide = package.find(OPF + "guide")
    if guide is not None:
        for reference in guide.findall(OPF + "reference"):
            check(package_name, _attr(reference, "href") or "", "GUIDE")
    return tuple(problems)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _ncx_problems(data: bytes) -> Tuple[str, ...]:
    try:
        root = ET.fromstring(data)
    except ET.ParseError as error:
        return ("NCX is not valid XML: {0}".format(error),)
    problems = []
    for element in root.iter():
        if _local_name(element.tag) != "navPoint":
            continue
        labels = [c for c in element if _local_name(c.tag) == "navLabel"]
        if not labels:
            problems.append("NCX navPoint has no navLabel")
        for label in labels:
            if not any(_local_name(c.tag) == "text" for c in label):
                problems.append("NCX navLabel has no text element")
        contents = [c for c in element if _local_name(c.tag) == "content"]
        if not contents:
            problems.append("NCX navPoint has no content element")
        elif not (_attr(contents[0], "src") or "").strip():
            problems.append("NCX content element has no src")
    return tuple(problems)


def _nav_document_problems(data: bytes) -> Tuple[str, ...]:
    try:
        root = ET.fromstring(data)
    except ET.ParseError as error:
        return ("navigation document is not valid XML: {0}".format(error),)
    problems = []
    for element in root.iter():
        if _local_name(element.tag) != "nav":
            continue
        if not any(_local_name(c.tag) == "ol" for c in element):
            problems.append("EPUB 3 nav element has no ol")
        for item in element.iter():
            if _local_name(item.tag) != "li":
                continue
            children = {_local_name(c.tag) for c in item}
            if "a" not in children and "span" not in children:
                problems.append("EPUB 3 li element has no a/span")
    return tuple(problems)


def _resolve_href(package_name: str, href: str) -> str:
    """Resolve a manifest href to a ZIP member path."""
    if not href:
        return ""
    parsed = urlsplit(href)
    if parsed.scheme or parsed.netloc:
        return ""
    path = unquote(parsed.path)
    if not path:
        return ""
    if path.startswith("/"):
        return posixpath.normpath(path.lstrip("/"))
    return posixpath.normpath(posixpath.join(posixpath.dirname(package_name), path))


def _spine_paths(package: ET.Element, package_name: str) -> set:
    manifest = package.find(OPF + "manifest")
    spine = package.find(OPF + "spine")
    if manifest is None or spine is None:
        return set()
    by_id = {
        (_attr(item, "id") or "").strip(): item
        for item in manifest.findall(OPF + "item")
    }
    paths = set()
    for ref in spine.findall(OPF + "itemref"):
        item = by_id.get((_attr(ref, "idref") or "").strip())
        if item is None:
            continue
        path = _resolve_href(package_name, _attr(item, "href") or "")
        if path:
            paths.add(path)
    return paths


def _sanitize_ncx(
    data: bytes,
    *,
    member_name: str = "",
    member_names: Optional[set] = None,
    spine_paths: Optional[set] = None,
) -> Optional[bytes]:
    """Add missing NCX labels/texts; drop navPoints that break spine links."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return None
    if "}" in root.tag:
        namespace = root.tag.split("}", 1)[0][1:]
    else:
        namespace = ""

    def tag(name: str) -> str:
        return "{%s}%s" % (namespace, name) if namespace else name

    changed = [False]

    def label_text(navpoint: ET.Element) -> str:
        contents = [c for c in navpoint if _local_name(c.tag) == "content"]
        source = (_attr(contents[0], "src") or "").strip() if contents else ""
        name = posixpath.basename(source)
        stem = name.rsplit(".", 1)[0] if "." in name else name
        text = stem.replace("_", " ").strip()
        return text or "Section"

    def fix(navpoint: ET.Element) -> bool:
        contents = [c for c in navpoint if _local_name(c.tag) == "content"]
        if not contents or not (_attr(contents[0], "src") or "").strip():
            return False
        if member_names is not None and spine_paths is not None:
            target = _resolve_href(
                member_name, _attr(contents[0], "src") or ""
            )
            if (
                not target
                or target not in member_names
                or target not in spine_paths
            ):
                return False
        labels = [c for c in navpoint if _local_name(c.tag) == "navLabel"]
        if not labels:
            label = ET.Element(tag("navLabel"))
            text = ET.SubElement(label, tag("text"))
            text.text = label_text(navpoint)
            navpoint.insert(0, label)
            changed[0] = True
            return True
        for label in labels:
            texts = [c for c in label if _local_name(c.tag) == "text"]
            if not texts:
                text = ET.SubElement(label, tag("text"))
                text.text = label_text(navpoint)
                changed[0] = True
            else:
                for text in texts:
                    if not (text.text or "").strip() and len(text) == 0:
                        text.text = label_text(navpoint)
                        changed[0] = True
        return True

    def walk(parent: ET.Element) -> None:
        for child in list(parent):
            if _local_name(child.tag) == "navPoint":
                if not fix(child):
                    parent.remove(child)
                    changed[0] = True
                    continue
                walk(child)
            else:
                walk(child)

    walk(root)
    if not changed[0]:
        return None
    return _serialize_default_namespace(root, namespace)


def _sanitize_nav_document(
    data: bytes,
    *,
    member_name: str = "",
    member_names: Optional[set] = None,
    spine_paths: Optional[set] = None,
) -> Optional[bytes]:
    """Replace nav-document anchors that do not point into the spine."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return None
    if member_names is None or spine_paths is None:
        return None
    changed = False
    parents = {child: parent for parent in root.iter() for child in parent}
    for anchor in list(root.iter()):
        if _local_name(anchor.tag) != "a":
            continue
        href = _attr(anchor, "href") or ""
        target = _resolve_href(member_name, href)
        valid = (
            bool(href)
            and not href.strip().startswith("#")
            and target
            and target in member_names
            and target in spine_paths
        )
        if valid:
            continue
        parent = parents.get(anchor)
        if parent is None:
            continue
        span = ET.Element(anchor.tag.replace("}a", "}span"))
        span.text = anchor.text
        for child in list(anchor):
            anchor.remove(child)
            span.append(child)
        parent.insert(list(parent).index(anchor), span)
        parent.remove(anchor)
        changed = True
    if not changed:
        return None
    if "}" in root.tag:
        namespace = root.tag.split("}", 1)[0][1:]
    else:
        namespace = ""
    return _serialize_default_namespace(root, namespace)


def _sanitize_guide(
    package: ET.Element, names: set, package_name: str
) -> None:
    guide = package.find(OPF + "guide")
    if guide is None:
        return
    spine_paths = _spine_paths(package, package_name)
    for reference in list(guide.findall(OPF + "reference")):
        target = _resolve_href(
            package_name, _attr(reference, "href") or ""
        )
        if not target or target not in names or target not in spine_paths:
            guide.remove(reference)


def _sanitize_cover_metadata(
    package: ET.Element, names: set, package_name: str, major: int
) -> None:
    manifest = package.find(OPF + "manifest")
    metadata = package.find(OPF + "metadata")
    if manifest is None or metadata is None:
        return
    items = manifest.findall(OPF + "item")
    by_id = {(_attr(item, "id") or "").strip(): item for item in items}

    def first_cover_image() -> Optional[ET.Element]:
        for item in items:
            media_type = _attr(item, "media-type") or ""
            href = _attr(item, "href") or ""
            if not media_type.startswith("image/"):
                continue
            if _resolve_href(package_name, href) not in names:
                continue
            if "cover" in ((_attr(item, "id") or "") + href).lower():
                return item
        return None

    for item in list(metadata.findall(OPF + "meta")):
        if (_attr(item, "name") or "").strip() != "cover":
            continue
        cover_id = (_attr(item, "content") or "").strip()
        cover_item = by_id.get(cover_id) if cover_id else None
        if (
            cover_item is not None
            and _resolve_href(package_name, _attr(cover_item, "href") or "")
            in names
        ):
            continue
        replacement = first_cover_image()
        if replacement is not None and (_attr(replacement, "id") or "").strip():
            item.set("content", (_attr(replacement, "id") or "").strip())
        else:
            metadata.remove(item)

    for item in items:
        properties = (_attr(item, "properties") or "").split()
        if "cover-image" not in properties:
            continue
        if _resolve_href(package_name, _attr(item, "href") or "") in names:
            continue
        remaining = " ".join(p for p in properties if p != "cover-image")
        if remaining:
            item.set("properties", remaining)
        else:
            item.attrib.pop("properties", None)


def _sanitize_spine(
    package: ET.Element, names: set, package_name: str
) -> None:
    manifest = package.find(OPF + "manifest")
    spine = package.find(OPF + "spine")
    if manifest is None or spine is None:
        return
    by_id = {
        (_attr(item, "id") or "").strip(): item
        for item in manifest.findall(OPF + "item")
    }
    for ref in list(spine.findall(OPF + "itemref")):
        idref = (_attr(ref, "idref") or "").strip()
        item = by_id.get(idref) if idref else None
        if item is None:
            spine.remove(ref)
            continue
        if _resolve_href(package_name, _attr(item, "href") or "") not in names:
            spine.remove(ref)


def _set_series_metadata(
    metadata_element: ET.Element, series: str, series_index: Decimal, major: int
) -> None:
    _remove_series_metadata(metadata_element)
    if major >= 3:
        collection = ET.SubElement(metadata_element, OPF + "meta")
        collection.set("property", "belongs-to-collection")
        collection.set("id", SERIES_COLLECTION_ID)
        collection.text = series

        collection_type = ET.SubElement(metadata_element, OPF + "meta")
        collection_type.set("refines", "#" + SERIES_COLLECTION_ID)
        collection_type.set("property", "collection-type")
        collection_type.text = "series"

        position = ET.SubElement(metadata_element, OPF + "meta")
        position.set("refines", "#" + SERIES_COLLECTION_ID)
        position.set("property", "group-position")
        position.text = _format_index(series_index)
        return

    series_element = ET.SubElement(metadata_element, OPF + "meta")
    series_element.set("name", "calibre:series")
    series_element.set("content", series)

    index_element = ET.SubElement(metadata_element, OPF + "meta")
    index_element.set("name", "calibre:series_index")
    index_element.set("content", _format_index(series_index))


def _remove_series_metadata(metadata_element: ET.Element) -> None:
    """Remove every pre-existing series/collection marker for this series."""
    metas = list(metadata_element.findall(OPF + "meta"))
    collection_types = {}
    for item in metas:
        if (_attr(item, "property") or "").strip() != "collection-type":
            continue
        refines = (_attr(item, "refines") or "").strip()
        if refines.startswith("#"):
            collection_types[refines[1:]] = (item.text or "").strip()

    removed = []
    removed_ids = set()
    for item in metas:
        name = (_attr(item, "name") or "").strip()
        prop = (_attr(item, "property") or "").strip()
        item_id = (_attr(item, "id") or "").strip()
        if name in {"calibre:series", "calibre:series_index"}:
            removed.append(item)
            continue
        if prop != "belongs-to-collection":
            continue
        collection_type = collection_types.get(item_id) if item_id else None
        if item_id == SERIES_COLLECTION_ID or collection_type in (None, "", "series"):
            removed.append(item)
            if item_id:
                removed_ids.add(item_id)

    for item in metas:
        if item in removed:
            continue
        prop = (_attr(item, "property") or "").strip()
        refines = (_attr(item, "refines") or "").strip()
        target = refines[1:] if refines.startswith("#") else ""
        item_id = (_attr(item, "id") or "").strip()
        if item_id == SERIES_COLLECTION_ID:
            removed.append(item)
        elif prop in {"collection-type", "group-position"} and (
            target in removed_ids or target == SERIES_COLLECTION_ID
        ):
            removed.append(item)

    for item in removed:
        try:
            metadata_element.remove(item)
        except ValueError:
            pass


def _serialize_default_namespace(
    root: ET.Element, namespace: str
) -> bytes:
    """Serialize XML with ``namespace`` as the default (unprefixed) namespace.

    Older/lightweight EPUB readers look for literal tags such as ``<spine>``;
    ElementTree prefers prefixed output (``<opf:spine>``), which those readers
    cannot find. Keeping the namespace declarations intact while dropping the
    element prefix yields standard EPUB markup that every reader accepts.
    """
    text = ET.tostring(root, encoding="unicode")
    local = root.tag.rsplit("}", 1)[-1] if "}" in root.tag else root.tag
    match = re.match(
        r"<([A-Za-z_][\w.\-]*):" + re.escape(local) + r"[\s>/]", text
    )
    if match is not None:
        prefix = match.group(1)
        text = text.replace("<" + prefix + ":", "<").replace(
            "</" + prefix + ":", "</"
        )
        text = text.replace(
            "<" + local,
            '<{0} xmlns="{1}"'.format(local, namespace),
            1,
        )
    declaration = '<?xml version="1.0" encoding="utf-8"?>\n'
    return (declaration + text).encode("utf-8")


def _format_index(value) -> str:
    from .naming import format_volume

    return format_volume(Decimal(value))


def _read_member(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes:
    """Read one member, tolerating archives with a bad CRC in that member."""
    try:
        return archive.read(info)
    except zipfile.BadZipFile:
        return _read_member_raw(archive, info)


def _read_member_raw(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes:
    """Decompress a member directly, skipping the CRC verification."""
    import zlib

    filename = archive.filename
    if not filename:
        raise ValueError("cannot recover a corrupt member from a memory stream")
    with open(filename, "rb") as handle:
        handle.seek(info.header_offset)
        header = handle.read(30)
        if len(header) < 30:
            raise ValueError("truncated ZIP local header")
        name_length = int.from_bytes(header[26:28], "little")
        extra_length = int.from_bytes(header[28:30], "little")
        handle.seek(info.header_offset + 30 + name_length + extra_length)
        raw = handle.read(info.compress_size)
    if info.compress_type == zipfile.ZIP_DEFLATED:
        return zlib.decompress(raw, -15)
    if info.compress_type == zipfile.ZIP_STORED:
        return raw
    raise ValueError(
        "cannot recover member {0!r} with compression type {1}".format(
            info.filename, info.compress_type
        )
    )


def _write_mimetype(archive: zipfile.ZipFile, output: zipfile.ZipFile) -> None:
    try:
        info = archive.getinfo("mimetype")
    except KeyError:
        return
    stored = zipfile.ZipInfo("mimetype", date_time=info.date_time)
    stored.compress_type = zipfile.ZIP_STORED
    stored.external_attr = info.external_attr
    output.writestr(stored, _read_member(archive, info))


def _copy_info(info: zipfile.ZipInfo) -> zipfile.ZipInfo:
    copied = zipfile.ZipInfo(info.filename, date_time=info.date_time)
    copied.compress_type = info.compress_type
    copied.external_attr = info.external_attr
    copied.internal_attr = info.internal_attr
    copied.create_system = info.create_system
    copied.comment = info.comment
    copied.extra = info.extra
    return copied


def spine_length(path: Path) -> int:
    """Number of distinct spine documents that resolve to manifest items."""
    with zipfile.ZipFile(path) as archive:
        package_name = find_package_document(archive)
        package = ET.fromstring(archive.read(package_name))
    return len(_spine_paths(package, package_name))
