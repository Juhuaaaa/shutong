"""Tests for the light novel EPUB metadata layer."""
from pathlib import Path
import tempfile
import unittest
import warnings
import zipfile
from xml.etree import ElementTree as ET

from shutong.engine.kinds.novel import epub


OPF = epub.OPF
DC = epub.DC


def build_epub(
    path: Path,
    *,
    version: str = "2.0",
    title: str = "Book Title",
    language: str = "zh-CN",
    creators=("Author",),
    creator_roles=None,
    series: str = "",
    series_index: str = "",
    extra_manifest_items=(),
    spine_idrefs=(),
    ncx_xml: str = "",
    cover_meta_id: str = "",
    nav_xml: str = "",
    guide_href: str = "",
) -> None:
    package = ET.Element(OPF + "package", {"version": version, "unique-identifier": "bookid"})
    metadata = ET.SubElement(package, OPF + "metadata")
    identifier = ET.SubElement(metadata, DC + "identifier", {"id": "bookid"})
    identifier.text = "urn:uuid:00000000-0000-0000-0000-000000000000"
    title_element = ET.SubElement(metadata, DC + "title")
    title_element.text = title
    for number, creator in enumerate(creators):
        element = ET.SubElement(metadata, DC + "creator", {"id": "creator%d" % number})
        element.text = creator
        role = (creator_roles or {}).get(creator)
        if role and version.startswith("3"):
            ET.SubElement(metadata, OPF + "meta", {"refines": "#creator%d" % number, "property": "role",
                                                   "scheme": "marc:relators"}).text = role
        elif role:
            element.set(OPF + "role", role)
    language_element = ET.SubElement(metadata, DC + "language")
    language_element.text = language
    if series:
        if version.startswith("3"):
            collection = ET.SubElement(
                metadata,
                OPF + "meta",
                {"property": "belongs-to-collection", "id": "series"},
            )
            collection.text = series
            position = ET.SubElement(
                metadata,
                OPF + "meta",
                {"property": "group-position", "refines": "#series"},
            )
            position.text = series_index
        else:
            ET.SubElement(
                metadata,
                OPF + "meta",
                {"name": "calibre:series", "content": series},
            )
            ET.SubElement(
                metadata,
                OPF + "meta",
                {"name": "calibre:series_index", "content": series_index},
            )
    manifest = ET.SubElement(package, OPF + "manifest")
    ET.SubElement(
        manifest,
        OPF + "item",
        {
            "id": "chapter",
            "href": "text/ch1.xhtml",
            "media-type": "application/xhtml+xml",
        },
    )
    for extra in extra_manifest_items:
        ET.SubElement(manifest, OPF + "item", extra)
    if ncx_xml:
        ET.SubElement(
            manifest,
            OPF + "item",
            {
                "id": "ncx",
                "href": "toc.ncx",
                "media-type": "application/x-dtbncx+xml",
            },
        )
    if nav_xml:
        ET.SubElement(
            manifest,
            OPF + "item",
            {
                "id": "nav",
                "href": "nav.xhtml",
                "media-type": "application/xhtml+xml",
                "properties": "nav",
            },
        )
    if guide_href:
        guide = ET.SubElement(package, OPF + "guide")
        ET.SubElement(
            guide,
            OPF + "reference",
            {"type": "cover", "title": "Cover", "href": guide_href},
        )
    if cover_meta_id:
        ET.SubElement(
            manifest,
            OPF + "item",
            {
                "id": "cover-img",
                "href": "Images/cover.jpg",
                "media-type": "image/jpeg",
            },
        )
        ET.SubElement(
            metadata, OPF + "meta", {"name": "cover", "content": cover_meta_id}
        )
    spine_attributes = {"toc": "ncx"} if ncx_xml else {}
    spine = ET.SubElement(package, OPF + "spine", spine_attributes)
    for idref in spine_idrefs or ("chapter",):
        ET.SubElement(spine, OPF + "itemref", {"idref": idref})

    container = ET.Element(
        "{%s}container" % epub.CONTAINER_NAMESPACE,
        {"version": "1.0"},
    )
    rootfiles = ET.SubElement(container, "{%s}rootfiles" % epub.CONTAINER_NAMESPACE)
    ET.SubElement(
        rootfiles,
        "{%s}rootfile" % epub.CONTAINER_NAMESPACE,
        {
            "full-path": "OEBPS/content.opf",
            "media-type": "application/oebps-package+xml",
        },
    )

    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr(
            "META-INF/container.xml",
            ET.tostring(container, encoding="utf-8", xml_declaration=True),
        )
        archive.writestr(
            "OEBPS/content.opf",
            ET.tostring(package, encoding="utf-8", xml_declaration=True),
        )
        members = {"OEBPS/text/ch1.xhtml": "<html/>"}
        if cover_meta_id:
            members["OEBPS/Images/cover.jpg"] = b"\xff\xd8\xff"
        if ncx_xml:
            members["OEBPS/toc.ncx"] = ncx_xml
        if nav_xml:
            members["OEBPS/nav.xhtml"] = nav_xml
        for extra in extra_manifest_items:
            href = extra.get("href")
            if href and not href.startswith("/"):
                members.setdefault("OEBPS/" + href, "<html/>")
        for member_name, content in members.items():
            archive.writestr(member_name, content)


def make_ncx(text: str, src: str = "text/ch1.xhtml") -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'
        "<head></head><docTitle><text>测试</text></docTitle><navMap>"
        '<navPoint id="p1" playOrder="1"><navLabel><text>第一章</text></navLabel>'
        '<content src="{src}"/></navPoint>'
        '<navPoint id="p2" playOrder="2"><navLabel>{text}</navLabel>'
        '<content src="{src}"/></navPoint>'
        '<navPoint id="p3" playOrder="3"><navLabel><text>无内容</text></navLabel></navPoint>'
        "</navMap></ncx>"
    ).format(text=text, src=src)


def read_member(path: Path, name: str) -> bytes:
    with zipfile.ZipFile(path) as archive:
        return archive.read(name)


class EpubMetadataTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)

    def test_reads_existing_epub2_series(self) -> None:
        source = self.root / "source.epub"
        build_epub(source, series="Existing", series_index="3")
        metadata = epub.read_metadata(source)
        self.assertEqual("Existing", metadata.series)
        self.assertEqual("3", metadata.series_index)
        self.assertEqual("Book Title", metadata.title)

    def test_writes_epub2_kavita_metadata(self) -> None:
        source = self.root / "source.epub"
        destination = self.root / "output.epub"
        build_epub(source, creators=("既有作者",))
        epub.write_metadata(
            source,
            destination,
            epub.KavitaMetadata(
                series="测试系列",
                series_index=12,
                title="第十二卷",
                language="zh",
                authors=("新作者",),
                publisher="出版社",
                genres=("奇幻", "冒险"),
                description="系列简介",
                date="2021-02-03",
                web_url="https://bgm.tv/subject/1",
            ),
        )
        metadata = epub.read_metadata(destination)
        self.assertEqual("测试系列", metadata.series)
        self.assertEqual("12", metadata.series_index)
        self.assertEqual("第十二卷", metadata.title)
        self.assertEqual(("zh",), metadata.languages)
        self.assertEqual("出版社", metadata.publisher)
        self.assertEqual(("奇幻", "冒险"), metadata.subjects)
        self.assertEqual("系列简介", metadata.description)
        # The source's authors take the place of whatever the file said.
        self.assertEqual(("新作者",), metadata.creators)
        elements = _metadata_elements(destination)
        self.assertEqual(1, len(elements["calibre:series"]))
        self.assertEqual(1, len(elements["calibre:series_index"]))
        self.assertFalse(elements["belongs-to-collection"])

    def test_writes_epub3_collection_metadata(self) -> None:
        source = self.root / "source3.epub"
        destination = self.root / "output3.epub"
        build_epub(source, version="3.0")
        epub.write_metadata(
            source,
            destination,
            epub.KavitaMetadata(
                series="测试系列",
                series_index=epub.SPECIAL_VOLUME_INDEX,
                title="特别篇",
                authors=("作者",),
            ),
        )
        metadata = epub.read_metadata(destination)
        self.assertEqual("测试系列", metadata.series)
        self.assertEqual(str(epub.SPECIAL_VOLUME_INDEX), metadata.series_index)
        elements = _metadata_elements(destination)
        self.assertEqual(1, len(elements["belongs-to-collection"]))
        self.assertEqual(1, len(elements["group-position"]))
        self.assertFalse(elements["calibre:series"])

    def test_replaces_existing_epub3_series(self) -> None:
        source = self.root / "source.epub"
        destination = self.root / "output.epub"
        build_epub(source, version="3.0", series="旧系列", series_index="7")
        epub.write_metadata(
            source,
            destination,
            epub.KavitaMetadata(series="新系列", series_index=3, title="第三卷"),
        )
        metadata = epub.read_metadata(destination)
        self.assertEqual("新系列", metadata.series)
        self.assertEqual("3", metadata.series_index)
        elements = _metadata_elements(destination)
        self.assertEqual(1, len(elements["belongs-to-collection"]))
        self.assertEqual("新系列", elements["belongs-to-collection"][0].text)
        self.assertEqual(1, len(elements["group-position"]))
        self.assertEqual("3", elements["group-position"][0].text)

    def test_replaces_existing_epub2_series(self) -> None:
        source = self.root / "source.epub"
        destination = self.root / "output.epub"
        build_epub(source, series="旧系列", series_index="7")
        epub.write_metadata(
            source,
            destination,
            epub.KavitaMetadata(series="新系列", series_index=3, title="第三卷"),
        )
        metadata = epub.read_metadata(destination)
        self.assertEqual("新系列", metadata.series)
        self.assertEqual("3", metadata.series_index)

    def test_rebuilds_series_metadata_idempotently(self) -> None:
        source = self.root / "source.epub"
        first = self.root / "first.epub"
        second = self.root / "second.epub"
        build_epub(source)
        metadata = epub.KavitaMetadata(series="系列", series_index=2, title="第二卷")
        epub.write_metadata(source, first, metadata)
        epub.write_metadata(first, second, metadata)
        elements = _metadata_elements(second)
        self.assertEqual(1, len(elements["calibre:series"]))
        self.assertEqual(1, len(elements["calibre:series_index"]))
        self.assertEqual(1, len(elements["identifiers"]))

    def test_preserves_members_and_mimetype_order(self) -> None:
        source = self.root / "source.epub"
        destination = self.root / "output.epub"
        build_epub(source)
        with zipfile.ZipFile(source) as archive:
            source_names = archive.namelist()
        epub.write_metadata(
            source,
            destination,
            epub.KavitaMetadata(series="系列", series_index=1, title="第一卷"),
        )
        with zipfile.ZipFile(destination) as archive:
            names = archive.namelist()
            self.assertEqual(source_names, names)
            self.assertEqual("mimetype", names[0])
            self.assertEqual(zipfile.ZIP_STORED, archive.getinfo("mimetype").compress_type)

    def test_sanitizes_duplicate_manifest_hrefs(self) -> None:
        source = self.root / "source.epub"
        destination = self.root / "output.epub"
        build_epub(
            source,
            extra_manifest_items=[
                {"id": "main-css", "href": "styles/main.css", "media-type": "text/css"},
                {"id": "css", "href": "styles/main.css", "media-type": "text/css"},
            ],
        )
        self.assertTrue(epub.validate_package(source))
        epub.write_metadata(
            source,
            destination,
            epub.KavitaMetadata(series="系列", series_index=1, title="第一卷"),
        )
        self.assertEqual((), epub.validate_package(destination))
        with zipfile.ZipFile(destination) as archive:
            hrefs = [
                item.get("href")
                for item in _package(destination).find(OPF + "manifest").findall(
                    OPF + "item"
                )
            ]
            self.assertEqual(1, hrefs.count("styles/main.css"))
            self.assertIn("OEBPS/styles/main.css", archive.namelist())

    def test_sanitizes_duplicate_manifest_ids(self) -> None:
        source = self.root / "source.epub"
        destination = self.root / "output.epub"
        build_epub(
            source,
            extra_manifest_items=[
                {"id": "dup", "href": "text/a.xhtml", "media-type": "application/xhtml+xml"},
                {"id": "dup", "href": "text/b.xhtml", "media-type": "application/xhtml+xml"},
            ],
        )
        self.assertTrue(epub.validate_package(source))
        epub.write_metadata(
            source,
            destination,
            epub.KavitaMetadata(series="系列", series_index=1, title="第一卷"),
        )
        self.assertEqual((), epub.validate_package(destination))

    def test_spine_references_follow_merged_manifest_items(self) -> None:
        source = self.root / "source.epub"
        destination = self.root / "output.epub"
        build_epub(
            source,
            extra_manifest_items=[
                {
                    "id": "chapter-dup",
                    "href": "text/ch1.xhtml",
                    "media-type": "application/xhtml+xml",
                }
            ],
            spine_idrefs=("chapter", "chapter-dup"),
        )
        epub.write_metadata(
            source,
            destination,
            epub.KavitaMetadata(series="系列", series_index=1, title="第一卷"),
        )
        self.assertEqual((), epub.validate_package(destination))
        spine = _package(destination).find(OPF + "spine")
        idrefs = [ref.get("idref") for ref in spine.findall(OPF + "itemref")]
        self.assertEqual(["chapter"], idrefs)

    def test_drops_ncx_links_outside_spine(self) -> None:
        source = self.root / "source.epub"
        destination = self.root / "output.epub"
        ncx = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'
            "<head></head><docTitle><text>测试</text></docTitle><navMap>"
            '<navPoint id="ok" playOrder="1"><navLabel><text>正文</text></navLabel>'
            '<content src="text/ch1.xhtml"/></navPoint>'
            '<navPoint id="bad" playOrder="2"><navLabel><text>不在 spine</text></navLabel>'
            '<content src="text/extra.xhtml"/></navPoint>'
            "</navMap></ncx>"
        )
        build_epub(
            source,
            ncx_xml=ncx,
            extra_manifest_items=[
                {
                    "id": "extra",
                    "href": "text/extra.xhtml",
                    "media-type": "application/xhtml+xml",
                }
            ],
        )
        self.assertTrue(epub.validate_package(source))
        epub.write_metadata(
            source,
            destination,
            epub.KavitaMetadata(series="系列", series_index=1, title="第一卷"),
        )
        self.assertEqual((), epub.validate_package(destination))
        ncx_text = read_member(destination, "OEBPS/toc.ncx").decode("utf-8")
        self.assertNotIn('id="bad"', ncx_text)
        self.assertIn('id="ok"', ncx_text)

    def test_replaces_invalid_nav_links_with_spans(self) -> None:
        source = self.root / "source.epub"
        destination = self.root / "output.epub"
        nav = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<html xmlns="http://www.w3.org/1999/xhtml" '
            'xmlns:epub="http://www.idpf.org/2007/ops"><body>'
            '<nav epub:type="toc"><ol>'
            '<li><a href="text/ch1.xhtml">正文</a></li>'
            '<li><a href="#toc">目录</a></li>'
            '<li><a href="text/missing.xhtml">缺失</a></li>'
            "</ol></nav></body></html>"
        )
        build_epub(source, nav_xml=nav)
        self.assertTrue(epub.validate_package(source))
        epub.write_metadata(
            source,
            destination,
            epub.KavitaMetadata(series="系列", series_index=1, title="第一卷"),
        )
        self.assertEqual((), epub.validate_package(destination))
        nav_text = read_member(destination, "OEBPS/nav.xhtml").decode("utf-8")
        self.assertIn("text/ch1.xhtml", nav_text)
        nav_root = ET.fromstring(nav_text.encode("utf-8"))
        spans = [
            element
            for element in nav_root.iter()
            if element.tag.rsplit("}", 1)[-1] == "span"
            and (element.text or "").strip()
        ]
        self.assertEqual(["目录", "缺失"], [span.text.strip() for span in spans])

    def test_removes_invalid_guide_references(self) -> None:
        source = self.root / "source.epub"
        destination = self.root / "output.epub"
        build_epub(source, guide_href="Text/cover.xhtml")
        self.assertTrue(epub.validate_package(source))
        epub.write_metadata(
            source,
            destination,
            epub.KavitaMetadata(series="系列", series_index=1, title="第一卷"),
        )
        self.assertEqual((), epub.validate_package(destination))
        guide = _package(destination).find(OPF + "guide")
        self.assertIsNotNone(guide)
        self.assertEqual([], guide.findall(OPF + "reference"))

    def test_sanitizes_missing_ncx_labels_and_content(self) -> None:
        source = self.root / "source.epub"
        destination = self.root / "output.epub"
        build_epub(
            source,
            ncx_xml=make_ncx(""),
        )
        self.assertTrue(epub.validate_package(source))
        epub.write_metadata(
            source,
            destination,
            epub.KavitaMetadata(series="系列", series_index=1, title="第一卷"),
        )
        self.assertEqual((), epub.validate_package(destination))
        ncx = read_member(destination, "OEBPS/toc.ncx").decode("utf-8")
        self.assertIn("text/ch1", ncx)
        self.assertNotIn('id="p3"', ncx)

    def test_repairs_missing_cover_metadata(self) -> None:
        source = self.root / "source.epub"
        destination = self.root / "output.epub"
        build_epub(source, cover_meta_id="does-not-exist")
        self.assertTrue(epub.validate_package(source))
        epub.write_metadata(
            source,
            destination,
            epub.KavitaMetadata(series="系列", series_index=1, title="第一卷"),
        )
        self.assertEqual((), epub.validate_package(destination))
        package = _package(destination)
        covers = [
            item
            for item in package.find(OPF + "metadata").findall(OPF + "meta")
            if (item.get("name") or "") == "cover"
        ]
        self.assertEqual(1, len(covers))
        self.assertEqual("cover-img", covers[0].get("content"))

    def test_deduplicates_zip_members(self) -> None:
        source = self.root / "source.epub"
        destination = self.root / "output.epub"
        build_epub(source)
        members = []
        with zipfile.ZipFile(source) as archive:
            for info in archive.infolist():
                members.append((info, archive.read(info)))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with zipfile.ZipFile(source, "w") as archive:
                for info, data in members:
                    archive.writestr(info, data)
                archive.writestr("OEBPS/text/ch1.xhtml", b"<html/>")
        epub.write_metadata(
            source,
            destination,
            epub.KavitaMetadata(series="系列", series_index=1, title="第一卷"),
        )
        with zipfile.ZipFile(destination) as archive:
            names = archive.namelist()
        self.assertEqual(1, names.count("OEBPS/text/ch1.xhtml"))

    def test_recovers_member_with_bad_crc(self) -> None:
        source = self.root / "source.epub"
        destination = self.root / "output.epub"
        build_epub(source)
        raw = source.read_bytes()
        corrupted = raw.replace(b"<html/>", b"<htam/>", 1)
        self.assertNotEqual(raw, corrupted)
        source.write_bytes(corrupted)
        epub.write_metadata(
            source,
            destination,
            epub.KavitaMetadata(series="系列", series_index=1, title="第一卷"),
        )
        self.assertEqual((), epub.validate_package(destination))
        self.assertEqual(
            "系列", epub.read_metadata(destination).series
        )

    def test_rejects_same_source_and_destination(self) -> None:
        source = self.root / "source.epub"
        build_epub(source)
        with self.assertRaises(ValueError):
            epub.write_metadata(
                source,
                source,
                epub.KavitaMetadata(series="系列", series_index=1, title="第一卷"),
            )

    def test_creates_opf_metadata_when_source_has_none(self) -> None:
        source = self.root / "source.epub"
        destination = self.root / "output.epub"
        build_epub(source, creators=())
        epub.write_metadata(
            source,
            destination,
            epub.KavitaMetadata(
                series="系列", series_index=5, title="第五卷", authors=("作者",)
            ),
        )
        metadata = epub.read_metadata(destination)
        self.assertEqual("系列", metadata.series)
        self.assertEqual(("作者",), metadata.creators)


    def _write_people(self, version: str, authors=("燦々SUN",), illustrators=("ももこ",)) -> Path:
        source = self.root / ("people%s.epub" % version)
        destination = self.root / ("people%s-out.epub" % version)
        build_epub(source, version=version, creators=("错误作者", "某译者"), creator_roles={"某译者": "trl"})
        epub.write_metadata(source, destination, epub.KavitaMetadata(
            series="艾莉同学", series_index=1, title="第一卷", authors=authors, illustrators=illustrators))
        return destination

    def test_epub2_authors_from_the_source_replace_the_file_s_and_illustrators_are_marked(self) -> None:
        output = self._write_people("2.0")
        self.assertEqual([("某译者", "trl"), ("燦々SUN", "aut"), ("ももこ", "ill")], _people(output))
        # EPUB 2's own way, for readers other than Kavita
        roles = {item.text: item.get(OPF + "role") for item in _package(output).iter(DC + "creator")}
        self.assertEqual({"某译者": "trl", "燦々SUN": "aut", "ももこ": "ill"}, roles)

    def test_epub3_authors_from_the_source_replace_the_file_s_and_illustrators_are_marked(self) -> None:
        output = self._write_people("3.0")
        self.assertEqual([("某译者", "trl"), ("燦々SUN", "aut"), ("ももこ", "ill")], _people(output))
        self.assertFalse([item for item in _package(output).iter(DC + "creator") if item.get(OPF + "role")])

    def test_without_authors_from_the_source_the_file_s_own_stay(self) -> None:
        output = self._write_people("3.0", authors=(), illustrators=())
        self.assertEqual([("错误作者", None), ("某译者", "trl")], _people(output))

    def test_writing_people_twice_does_not_pile_them_up(self) -> None:
        once = self._write_people("3.0")
        twice = self.root / "twice.epub"
        epub.write_metadata(once, twice, epub.KavitaMetadata(
            series="艾莉同学", series_index=1, title="第一卷", authors=("燦々SUN",), illustrators=("ももこ",)))
        self.assertEqual(_people(once), _people(twice))
        roles = [item for item in _package(twice).iter(OPF + "meta") if item.get("property") == "role"]
        self.assertEqual(3, len(roles))


def _people(path: Path) -> list:
    """Creators with the role Kavita gives them: only a marc:relators refinement counts there."""
    metadata = _package(path).find(OPF + "metadata")
    roles = {(item.get("refines") or "")[1:]: (item.text or item.get("content") or "").strip()
             for item in metadata.findall(OPF + "meta")
             if item.get("property") == "role" and item.get("scheme") in (None, "marc:relators")}
    return [((item.text or "").strip(), roles.get(item.get("id") or ""))
            for item in metadata.findall(DC + "creator")]


def _package(path: Path) -> ET.Element:
    with zipfile.ZipFile(path) as archive:
        package_name = epub.find_package_document(archive)
        return ET.fromstring(archive.read(package_name))


def _metadata_elements(path: Path) -> dict:
    with zipfile.ZipFile(path) as archive:
        package_name = epub.find_package_document(archive)
        package = ET.fromstring(archive.read(package_name))
    metadata = package.find(OPF + "metadata")
    assert metadata is not None
    counts = {
        "calibre:series": [],
        "calibre:series_index": [],
        "belongs-to-collection": [],
        "group-position": [],
        "identifiers": [],
    }
    for item in metadata.findall(OPF + "meta"):
        name = (item.get("name") or "").strip()
        property_name = (item.get("property") or "").strip()
        if name in counts:
            counts[name].append(item)
        if property_name in counts:
            counts[property_name].append(item)
    counts["identifiers"] = metadata.findall(DC + "identifier")
    return counts

    def test_spine_length_counts_resolvable_itemrefs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "book.epub"
            build_epub(
                path,
                extra_manifest_items=(
                    {"id": "ch2", "href": "text/ch2.xhtml", "media-type": "application/xhtml+xml"},
                ),
                spine_idrefs=("chapter", "ch2", "missing"),
            )
            self.assertEqual(epub.spine_length(path), 2)


if __name__ == "__main__":
    unittest.main()
