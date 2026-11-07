import io
import shutil
from pathlib import Path
import stat
import subprocess
import tarfile
import tempfile
import unittest
from unittest import mock
import zipfile

from shutong.engine.kinds.base import BuildError
from shutong.engine.kinds.manga.cbz import (
    ArchiveLimits,
    _check_declared_size,
    collect_archive_pages,
    inspect_archive,
    verify_cbz,
    write_cbz,
)


def build_cbz(source, target, comic_info, limits):
    """The legacy one-call build expressed with the new collect + write API."""
    with tempfile.TemporaryDirectory() as work:
        pages = collect_archive_pages(source, Path(work), limits)
        return write_cbz(pages, comic_info, target)


def extract_non_zip(source, destination, limits=ArchiveLimits()):
    """Pre-listing checks run before any member is extracted, as in the legacy helper."""
    destination.mkdir(parents=True)
    return collect_archive_pages(source, destination, limits)


COMIC_INFO = b"<?xml version='1.0'?><ComicInfo><Series>Test</Series></ComicInfo>"
JPEG = b"\xff\xd8\xffsynthetic-jpeg"
PNG = b"\x89PNG\r\n\x1a\nsynthetic-png"
GIF = b"GIF89asynthetic-gif"
WEBP = b"RIFF\x10\x00\x00\x00WEBPsynthetic-webp"
AVIF = b"\x00\x00\x00\x18ftypavif\x00\x00\x00\x00avifmif1"


def tar_stream(members):
    """What `bsdtar -cf - --format pax @archive` writes: name -> bytes, or a TarInfo for special entries."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for name, data in members.items():
            if isinstance(data, tarfile.TarInfo):
                archive.addfile(data)
                continue
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def bsdtar_stream(source):
    return ["bsdtar", "-cf", "-", "--format", "pax", "@" + str(source)]


class CountingStream(io.BytesIO):

    def __init__(self, data):
        super().__init__(data)
        self.bytes_read = 0

    def read(self, size=-1):
        data = super().read(size)
        self.bytes_read += len(data)
        return data


class FakeProcess:
    def __init__(self, data):
        self.stdout = CountingStream(data)
        self.stderr = io.BytesIO()
        self.returncode = None
        self.killed = False

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self):
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


class ArchiveTests(unittest.TestCase):
    def test_default_limit_fits_webtoon_volumes(self):
        # Long-strip webtoon packs cut each chapter into dozens of images: 我独自升级 holds 9802 in one zip.
        self.assertGreaterEqual(ArchiveLimits().max_files, 9802)

    def setUp(self):
        # These legacy cases mock subprocess and assert the exact bsdtar argv; pin the
        # executable name so they do not depend on what the host has installed.
        library_patcher = mock.patch("shutong.engine.kinds.manga.cbz._USE_LIBARCHIVE", False)
        library_patcher.start()
        self.addCleanup(library_patcher.stop)
        patcher = mock.patch("shutong.engine.kinds.manga.cbz._bsdtar", return_value="bsdtar")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_builds_rooted_cbz_with_natural_page_order_and_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.zip"
            target = root / "output.cbz"
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr("book/10.jpg", b"\xff\xd8\xffpage10")
                archive.writestr("book/2.jpg", b"\xff\xd8\xffpage2")
                archive.writestr("book/.DS_Store", b"junk")
            build_cbz(
                source,
                target,
                COMIC_INFO,
                ArchiveLimits(),
            )
            report = verify_cbz(target)
            self.assertEqual(report.page_count, 2)
            with zipfile.ZipFile(target) as archive:
                self.assertEqual(archive.namelist(), ["001.jpg", "002.jpg", "ComicInfo.xml"])

    def test_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "bad.zip"
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr("../escape.jpg", b"\xff\xd8\xffbad")
            with self.assertRaisesRegex(ValueError, "unsafe archive path"):
                build_cbz(source, Path(directory) / "out.cbz", b"<ComicInfo />", ArchiveLimits())

    def test_detects_supported_images_by_signature_and_uses_safe_extensions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.cbz"
            target = root / "output.cbz"
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr("5.exe", AVIF)
                archive.writestr("4.txt", WEBP)
                archive.writestr("3.bin", GIF)
                archive.writestr("2.webp", PNG)
                archive.writestr("1.png", JPEG)
                archive.writestr("cover.jpg", b"not an image")
                archive.writestr("ComicInfo.xml", b"<ComicInfo><Series>Old</Series></ComicInfo>")

            build_cbz(source, target, COMIC_INFO, ArchiveLimits())

            with zipfile.ZipFile(target) as archive:
                self.assertEqual(
                    archive.namelist(),
                    ["001.jpg", "002.png", "003.gif", "004.webp", "005.avif", "ComicInfo.xml"],
                )
                self.assertEqual(archive.read("ComicInfo.xml"), COMIC_INFO)

    def test_inspection_reports_valid_pages_and_all_uncompressed_input_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.zip"
            junk = b"discarded"
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr("1.jpg", JPEG)
                archive.writestr("notes.txt", junk)

            report = inspect_archive(source, ArchiveLimits())

            self.assertEqual(report.page_count, 1)
            self.assertEqual(report.uncompressed_bytes, len(JPEG) + len(junk))

    def test_rejects_absolute_windows_and_symlink_zip_entries(self):
        unsafe_names = ["/absolute.jpg", "C:/windows.jpg", "//server/share.jpg"]
        for unsafe_name in unsafe_names:
            with self.subTest(name=unsafe_name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = root / "bad.zip"
                with zipfile.ZipFile(source, "w") as archive:
                    archive.writestr(unsafe_name, JPEG)
                with self.assertRaisesRegex(ValueError, "unsafe archive path"):
                    build_cbz(source, root / "out.cbz", COMIC_INFO, ArchiveLimits())

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "symlink.zip"
            link = zipfile.ZipInfo("page.jpg")
            link.create_system = 3
            link.external_attr = (stat.S_IFLNK | 0o777) << 16
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr(link, b"elsewhere")
            with self.assertRaisesRegex(ValueError, "link"):
                build_cbz(source, root / "out.cbz", COMIC_INFO, ArchiveLimits())

    def test_rejects_nul_in_original_zip_entry_name(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "bad.zip"
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr("safe.jpg", JPEG)
            source.write_bytes(source.read_bytes().replace(b"safe.jpg", b"bad\x00.jpg"))

            with self.assertRaisesRegex(ValueError, "unsafe archive path"):
                build_cbz(source, root / "out.cbz", COMIC_INFO, ArchiveLimits())

    def test_rejects_invalid_xml_and_leaves_no_target_or_temporary_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.zip"
            target = root / "output.cbz"
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr("1.jpg", JPEG)

            with self.assertRaises(ValueError):
                build_cbz(source, target, b"<ComicInfo>", ArchiveLimits())

            self.assertFalse(target.exists())
            self.assertEqual([source], list(root.iterdir()))

    def test_enforces_file_count_size_total_and_compression_ratio_limits(self):
        cases = [
            (ArchiveLimits(max_files=1), [("1.jpg", JPEG), ("junk", b"x")], "too many files"),
            (ArchiveLimits(max_file_bytes=4), [("1.jpg", JPEG)], "file size limit"),
            (ArchiveLimits(max_total_bytes=4), [("1.jpg", JPEG)], "total size limit"),
            (ArchiveLimits(max_compression_ratio=1), [("1.jpg", JPEG + b"0" * 4096)], "compression ratio"),
        ]
        for limits, entries, message in cases:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = root / "source.zip"
                with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                    for name, data in entries:
                        archive.writestr(name, data)
                with self.assertRaisesRegex(ValueError, message):
                    build_cbz(source, root / "output.cbz", COMIC_INFO, limits)
                self.assertFalse((root / "output.cbz").exists())

    def test_ratio_limit_tolerates_near_uniform_pages_but_rejects_bombs(self):
        limits = ArchiveLimits()
        # A real 2144x3204 JPEG cover was observed compressing ~212x; such
        # near-uniform pages must not be mistaken for a decompression bomb.
        page = zipfile.ZipInfo("2.jpg")
        page.file_size = 108363
        page.compress_size = 538
        _check_declared_size(page, limits, 0)

        bomb = zipfile.ZipInfo("bomb.jpg")
        bomb.file_size = 108363
        bomb.compress_size = 20
        with self.assertRaisesRegex(ValueError, "compression ratio"):
            _check_declared_size(bomb, limits, 0)

    def test_verify_rejects_bad_metadata_names_pages_and_limits(self):
        cases = [
            ([('001.jpg', JPEG), ('ComicInfo.xml', b'<ComicInfo>')], "invalid ComicInfo.xml"),
            ([('001.jpg', JPEG), ('comicinfo.xml', COMIC_INFO)], "exactly one root ComicInfo.xml"),
            ([('001.jpg', JPEG), ('nested/ComicInfo.xml', COMIC_INFO)], "exactly one root ComicInfo.xml"),
            ([('001.jpg', JPEG), ('ComicInfo.xml', COMIC_INFO), ('COMICINFO.XML', COMIC_INFO)], "exactly one root ComicInfo.xml"),
            ([('nested/001.jpg', JPEG), ('ComicInfo.xml', COMIC_INFO)], "unsafe CBZ page name"),
            ([('001.png', JPEG), ('ComicInfo.xml', COMIC_INFO)], "page extension"),
            ([('001.jpg', b'fake'), ('ComicInfo.xml', COMIC_INFO)], "invalid CBZ page"),
            ([('ComicInfo.xml', COMIC_INFO)], "no valid images"),
        ]
        for entries, message in cases:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as directory:
                target = Path(directory) / "bad.cbz"
                with zipfile.ZipFile(target, "w") as archive:
                    for name, data in entries:
                        archive.writestr(name, data)
                with self.assertRaisesRegex(ValueError, message):
                    verify_cbz(target)

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "large.cbz"
            with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("001.jpg", JPEG + b"0" * 1024)
                archive.writestr("ComicInfo.xml", COMIC_INFO)
            with self.assertRaisesRegex(ValueError, "file size limit"):
                verify_cbz(target, ArchiveLimits(max_file_bytes=32))
            with self.assertRaisesRegex(ValueError, "total size limit"):
                verify_cbz(target, ArchiveLimits(max_total_bytes=32))
            with self.assertRaisesRegex(ValueError, "compression ratio"):
                verify_cbz(target, ArchiveLimits(max_compression_ratio=1))

    def test_verify_validates_counts_and_uniqueness_across_directory_entries(self):
        cases = [
            (["../unsafe/"], ArchiveLimits(), "unsafe archive path"),
            (["Folder/", "folder/"], ArchiveLimits(), "duplicate case-variant"),
            (["extra/"], ArchiveLimits(max_files=2), "too many files"),
            (["extra/"], ArchiveLimits(), "directory entries"),
        ]
        for directories, limits, message in cases:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as directory:
                target = Path(directory) / "bad.cbz"
                with zipfile.ZipFile(target, "w") as archive:
                    archive.writestr("001.jpg", JPEG)
                    archive.writestr("ComicInfo.xml", COMIC_INFO)
                    for name in directories:
                        archive.writestr(name, b"")
                with self.assertRaisesRegex(ValueError, message):
                    verify_cbz(target, limits)

    def test_rejects_zip_directory_mode_without_directory_name(self):
        forged_names = ["001.jpg", "ComicInfo.xml"]
        for forged_name in forged_names:
            with self.subTest(name=forged_name), tempfile.TemporaryDirectory() as directory:
                target = Path(directory) / "bad.cbz"
                forged = zipfile.ZipInfo(forged_name)
                forged.create_system = 3
                forged.external_attr = (stat.S_IFDIR | 0o755) << 16
                with zipfile.ZipFile(target, "w") as archive:
                    if forged_name != "001.jpg":
                        archive.writestr("001.jpg", JPEG)
                    archive.writestr(forged, JPEG if forged_name == "001.jpg" else COMIC_INFO)
                    if forged_name != "ComicInfo.xml":
                        archive.writestr("ComicInfo.xml", COMIC_INFO)

                with self.assertRaisesRegex(ValueError, "directory mode"):
                    verify_cbz(target)

    def test_source_rejects_inconsistent_zip_directory_mode_and_name(self):
        cases = [
            ("forged", stat.S_IFDIR, JPEG),
            ("regular/", stat.S_IFREG, b""),
        ]
        for name, file_type, data in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = root / "source.zip"
                forged = zipfile.ZipInfo(name)
                forged.create_system = 3
                forged.external_attr = (file_type | 0o755) << 16
                with zipfile.ZipFile(source, "w") as archive:
                    archive.writestr(forged, data)
                    archive.writestr("001.jpg", JPEG)
                with self.assertRaisesRegex(ValueError, "directory"):
                    build_cbz(source, root / "output.cbz", COMIC_INFO, ArchiveLimits())

    def test_non_zip_uses_prelisting_and_argument_array_extraction(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.7z"
            source.write_bytes(b"synthetic archive container" * 4)
            target = root / "output.cbz"

            def run_bsdtar(arguments, **kwargs):
                if arguments[1] == "-tf":
                    return subprocess.CompletedProcess(arguments, 0, "book/2.jpg\nbook/1.png\n", "")
                listing = "-rw-r--r--  0 user group {0} Jan 1 00:00 book/2.jpg\n".format(len(JPEG))
                listing += "-rw-r--r--  0 user group {0} Jan 1 00:00 book/1.png\n".format(len(PNG))
                return subprocess.CompletedProcess(arguments, 0, listing, "")

            process = FakeProcess(tar_stream({"book/2.jpg": JPEG, "book/1.png": PNG}))

            with mock.patch("shutong.engine.kinds.manga.cbz.subprocess.run", side_effect=run_bsdtar) as runner, mock.patch(
                "shutong.engine.kinds.manga.cbz.subprocess.Popen", return_value=process
            ) as opener:
                build_cbz(source, target, COMIC_INFO, ArchiveLimits(max_compression_ratio=10))

            expected_options = {"check": False, "capture_output": True, "text": True}
            self.assertEqual(runner.call_count, 2)
            snapshot = str(source)  # read in place: no copy of the whole archive first
            self.assertEqual(runner.call_args_list[0], mock.call(["bsdtar", "-tf", snapshot], **expected_options))
            self.assertEqual(runner.call_args_list[1], mock.call(["bsdtar", "-tvf", snapshot], **expected_options))
            # One pass over the archive: reading member by member re-read a solid rar once per page.
            self.assertEqual([item.args[0] for item in opener.call_args_list], [bsdtar_stream(source)])
            self.assertEqual(process.returncode, 0)
            with zipfile.ZipFile(target) as archive:
                self.assertEqual(archive.namelist(), ["001.png", "002.jpg", "ComicInfo.xml"])

    def test_non_zip_source_replaced_while_reading_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.7z"
            source.write_bytes(b"synthetic archive container" * 4)
            target = root / "output.cbz"

            def run_bsdtar(arguments, **kwargs):
                if arguments[1] == "-tf":
                    source.write_bytes(b"replacement after listing")
                    return subprocess.CompletedProcess(arguments, 0, "book/1.jpg\n", "")
                listing = "-rw-r--r--  0 user group {0} Jan 1 00:00 book/1.jpg\n".format(len(JPEG))
                return subprocess.CompletedProcess(arguments, 0, listing, "")

            with mock.patch("shutong.engine.kinds.manga.cbz.subprocess.run", side_effect=run_bsdtar), mock.patch(
                "shutong.engine.kinds.manga.cbz.subprocess.Popen",
                return_value=FakeProcess(tar_stream({"book/1.jpg": JPEG})),
            ):
                with self.assertRaisesRegex(BuildError, "changed while being read"):
                    build_cbz(source, target, COMIC_INFO, ArchiveLimits())
            self.assertFalse(target.exists())

    @unittest.skipUnless(shutil.which("bsdtar"), "needs a real bsdtar")
    def test_non_zip_member_names_with_brackets_are_read_literally(self):
        # bsdtar treats a member name as a pattern: "[森繁]" would mean "森 or 繁" and match nothing.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "files" / "[森繁]櫻×櫻 Vol.01"
            folder.mkdir(parents=True)
            (folder / "YxY01-001*.jpg").write_bytes(JPEG)
            (folder / "YxY01-002?.png").write_bytes(PNG)
            source = root / "source.7z"
            subprocess.run(["bsdtar", "--format", "7zip", "-cf", str(source), "-C", str(root / "files"), "."], check=True)
            target = root / "output.cbz"
            build_cbz(source, target, COMIC_INFO, ArchiveLimits(max_compression_ratio=1000))
            with zipfile.ZipFile(target) as archive:
                self.assertEqual(archive.namelist(), ["001.jpg", "002.png", "ComicInfo.xml"])

    def test_non_zip_member_names_cannot_inject_bsdtar_options(self):
        for member_name in ["--use-compress-program=synthetic", "-C"]:
            with self.subTest(member=member_name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = root / "source.7z"
                source.write_bytes(b"synthetic archive")
                target = root / "output.cbz"

                def run_bsdtar(arguments, **kwargs):
                    if arguments[1] == "-tf":
                        return subprocess.CompletedProcess(arguments, 0, member_name + "\n", "")
                    listing = "-rw-r--r--  0 user group {0} Jan 1 00:00 {1}\n".format(
                        len(JPEG), member_name
                    )
                    return subprocess.CompletedProcess(arguments, 0, listing, "")

                process = FakeProcess(tar_stream({member_name: JPEG}))
                with mock.patch("shutong.engine.kinds.manga.cbz.subprocess.run", side_effect=run_bsdtar), mock.patch(
                    "shutong.engine.kinds.manga.cbz.subprocess.Popen", return_value=process
                ) as opener:
                    build_cbz(source, target, COMIC_INFO, ArchiveLimits())

                # Member names never reach the command line.
                self.assertEqual(opener.call_args.args[0], bsdtar_stream(source))

    def test_non_zip_size_is_bounded_before_any_bsdtar_call(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "oversized.7z"
            source.write_bytes(b"x" * 101)
            target = root / "output.cbz"

            with mock.patch("shutong.engine.kinds.manga.cbz.tempfile.tempdir", str(root)), mock.patch(
                "shutong.engine.kinds.manga.cbz.subprocess.run"
            ) as runner, mock.patch("shutong.engine.kinds.manga.cbz.subprocess.Popen") as opener:
                with self.assertRaisesRegex(ValueError, "archive size limit"):
                    build_cbz(source, target, COMIC_INFO, ArchiveLimits(max_total_bytes=100))

            runner.assert_not_called()
            opener.assert_not_called()
            self.assertEqual(list(root.iterdir()), [source])

    def test_non_zip_rejects_unsafe_prelisted_path_before_extraction(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.rar"
            source.write_bytes(b"synthetic")
            listed = subprocess.CompletedProcess([], 0, "../escape.jpg\n", "")
            with mock.patch("shutong.engine.kinds.manga.cbz.subprocess.run", return_value=listed) as runner:
                with self.assertRaisesRegex(ValueError, "unsafe archive path"):
                    extract_non_zip(source, root / "contents")
            self.assertEqual(runner.call_count, 1)

    def test_non_zip_rejects_hard_link_marker_before_extraction(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.cbr"
            source.write_bytes(b"synthetic")
            results = [
                subprocess.CompletedProcess([], 0, "page.jpg\n", ""),
                subprocess.CompletedProcess(
                    [], 0, "-rw-r--r--  0 user group 0 Jan 1 00:00 page.jpg link to target.jpg\n", ""
                ),
            ]
            with mock.patch("shutong.engine.kinds.manga.cbz.subprocess.run", side_effect=results) as runner:
                with self.assertRaisesRegex(ValueError, "link or special"):
                    extract_non_zip(source, root / "contents")
            self.assertEqual(runner.call_count, 2)

    def test_non_zip_rejects_declared_size_limit_before_extraction(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.7z"
            source.write_bytes(b"synthetic")
            results = [
                subprocess.CompletedProcess([], 0, "page.jpg\n", ""),
                subprocess.CompletedProcess([], 0, "-rw-r--r--  0 user group 500 Jan 1 00:00 page.jpg\n", ""),
            ]
            with mock.patch("shutong.engine.kinds.manga.cbz.subprocess.run", side_effect=results) as runner:
                with self.assertRaisesRegex(ValueError, "file size limit"):
                    extract_non_zip(source, root / "contents", ArchiveLimits(max_file_bytes=100))
            self.assertEqual(runner.call_count, 2)

    def test_non_zip_rejects_duplicate_and_casefold_colliding_normalized_paths(self):
        cases = [
            "book/1.jpg\nbook/1.jpg\n",
            "Book/1.jpg\nbook/1.jpg\n",
            "book/1.jpg\nbook\\1.jpg\n",
        ]
        for listing in cases:
            with self.subTest(listing=listing), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = root / "source.7z"
                source.write_bytes(b"synthetic")
                listed = subprocess.CompletedProcess([], 0, listing, "")
                with mock.patch("shutong.engine.kinds.manga.cbz.subprocess.run", return_value=listed) as runner:
                    with self.assertRaisesRegex(ValueError, "duplicate archive path"):
                        extract_non_zip(source, root / "contents")
                self.assertEqual(runner.call_count, 1)

    def test_non_zip_stops_stream_when_actual_bytes_exceed_declared_size_and_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.cb7"
            source.write_bytes(b"synthetic archive")
            target = root / "output.cbz"

            def run_bsdtar(arguments, **kwargs):
                if arguments[1] == "-tf":
                    return subprocess.CompletedProcess(arguments, 0, "page.jpg\n", "")
                return subprocess.CompletedProcess(
                    arguments, 0, "-rw-r--r--  0 user group 5 Jan 1 00:00 page.jpg\n", ""
                )

            process = FakeProcess(tar_stream({"page.jpg": JPEG + b"x" * 100000}))

            with mock.patch("shutong.engine.kinds.manga.cbz.subprocess.run", side_effect=run_bsdtar), mock.patch(
                "shutong.engine.kinds.manga.cbz.subprocess.Popen", return_value=process
            ):
                with self.assertRaisesRegex(ValueError, "does not match listing"):
                    build_cbz(source, target, COMIC_INFO, ArchiveLimits(max_file_bytes=10))

            self.assertTrue(process.killed)
            self.assertLess(process.stdout.bytes_read, 50000)  # stopped at the header, not after the data
            self.assertFalse(target.exists())

    def test_non_zip_stream_refuses_entries_the_listing_did_not_show(self):
        link = tarfile.TarInfo("page.jpg")
        link.type = tarfile.SYMTYPE
        link.linkname = "/etc/passwd"
        cases = {
            "link": ({"page.jpg": link}, "link or special"),
            "unlisted": ({"page.jpg": JPEG, "extra.jpg": JPEG}, "not in the listing"),
            "missing": ({}, "missing from the archive"),
            "traversal": ({"../page.jpg": JPEG}, "unsafe archive path"),
        }
        for label, (members, message) in cases.items():
            with self.subTest(label), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = root / "source.rar"
                source.write_bytes(b"synthetic archive")

                def run_bsdtar(arguments, **kwargs):
                    if arguments[1] == "-tf":
                        return subprocess.CompletedProcess(arguments, 0, "page.jpg\n", "")
                    listing = "-rw-r--r--  0 user group {0} Jan 1 00:00 page.jpg\n".format(len(JPEG))
                    return subprocess.CompletedProcess(arguments, 0, listing, "")

                process = FakeProcess(tar_stream(members))
                with mock.patch("shutong.engine.kinds.manga.cbz.subprocess.run", side_effect=run_bsdtar), mock.patch(
                    "shutong.engine.kinds.manga.cbz.subprocess.Popen", return_value=process
                ):
                    with self.assertRaisesRegex(ValueError, message):
                        extract_non_zip(source, root / "contents")

    def test_non_zip_bsdtar_failure_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.rar"
            source.write_bytes(b"synthetic archive")

            def run_bsdtar(arguments, **kwargs):
                if arguments[1] == "-tf":
                    return subprocess.CompletedProcess(arguments, 0, "page.jpg\n", "")
                listing = "-rw-r--r--  0 user group {0} Jan 1 00:00 page.jpg\n".format(len(JPEG))
                return subprocess.CompletedProcess(arguments, 0, listing, "")

            process = FakeProcess(tar_stream({"page.jpg": JPEG}))
            process.wait = lambda: 1
            with mock.patch("shutong.engine.kinds.manga.cbz.subprocess.run", side_effect=run_bsdtar), mock.patch(
                "shutong.engine.kinds.manga.cbz.subprocess.Popen", return_value=process
            ):
                with self.assertRaisesRegex(BuildError, "bsdtar"):
                    extract_non_zip(source, root / "contents")

    @unittest.skipUnless(shutil.which("bsdtar"), "needs a real bsdtar")
    def test_non_zip_many_pages_are_read_in_one_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "files" / "第01卷"
            folder.mkdir(parents=True)
            for number in range(1, 41):
                (folder / "{0:03d}.jpg".format(number)).write_bytes(JPEG + bytes([number]) * 50)
            source = root / "source.7z"
            subprocess.run(["bsdtar", "--format", "7zip", "-cf", str(source), "-C", str(root / "files"), "."], check=True)
            target = root / "output.cbz"
            with mock.patch("shutong.engine.kinds.manga.cbz.subprocess.Popen", wraps=subprocess.Popen) as opener:
                build_cbz(source, target, COMIC_INFO, ArchiveLimits(max_compression_ratio=1000))
            # subprocess.run() also goes through Popen: count only the reads of the pages.
            reads = [call.args[0] for call in opener.call_args_list if call.args[0][1] not in ("-tf", "-tvf")]
            self.assertEqual(reads, [bsdtar_stream(source)])
            with zipfile.ZipFile(target) as archive:
                self.assertEqual(len(archive.namelist()), 41)
                self.assertEqual(archive.read("040.jpg"), JPEG + bytes([40]) * 50)


class EngineCbzTests(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.root = Path(self._directory.name)
        self.work = self.root / "work"
        self.work.mkdir()
        self.target = self.root / "out.cbz"

    def _zip(self, name, members, encrypted=False):
        path = self.root / name
        with zipfile.ZipFile(path, "w") as archive:
            for member, data in members.items():
                archive.writestr(member, data)
        if encrypted:
            # writestr() resets flag_bits, so mark encryption in both headers by hand.
            data = bytearray(path.read_bytes())
            for signature, offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
                position = data.find(signature)
                data[position + offset] |= 0x1
            path.write_bytes(bytes(data))
        return path

    def test_bad_inputs_raise_build_error_and_leave_no_target(self):
        empty = self.root / "empty.zip"
        empty.write_bytes(b"")
        broken = self.root / "broken.zip"
        broken.write_bytes(b"PK\x03\x04garbage")
        inner = self._zip("inner.zip", {"01.jpg": JPEG})
        nested = self._zip("nested.zip", {"inner.zip": inner.read_bytes()})
        encrypted = self._zip("encrypted.zip", {"01.jpg": JPEG}, encrypted=True)
        for source in (empty, broken, nested, encrypted):
            with self.subTest(source=source.name):
                work = self.work / source.stem
                work.mkdir()
                with self.assertRaises(BuildError):
                    collect_archive_pages(source, work)
                self.assertFalse(self.target.exists())

    def test_write_cbz_numbers_pages(self):
        source = self._zip("src.zip", {"b/10.jpg": JPEG, "b/2.png": PNG, "b/1.jpg": JPEG})
        pages = collect_archive_pages(source, self.work)
        report = write_cbz(pages, COMIC_INFO, self.target)
        self.assertEqual(report.page_count, 3)
        with zipfile.ZipFile(self.target) as archive:
            self.assertEqual(archive.namelist(), ["001.jpg", "002.png", "003.jpg", "ComicInfo.xml"])
        verify_cbz(self.target)

    def test_write_cbz_stores_pages_without_recompressing(self):
        # Images are already compressed: deflating them again costs seconds per volume and saves ~2 %.
        source = self._zip("src.zip", {"1.jpg": JPEG, "2.png": PNG})
        pages = collect_archive_pages(source, self.work)
        write_cbz(pages, COMIC_INFO, self.target)
        with zipfile.ZipFile(self.target) as archive:
            types = {info.filename: info.compress_type for info in archive.infolist()}
        self.assertEqual(types, {"001.jpg": zipfile.ZIP_STORED, "002.png": zipfile.ZIP_STORED,
                                 "ComicInfo.xml": zipfile.ZIP_DEFLATED})

    def test_write_cbz_leaves_verification_to_the_publisher(self):
        source = self._zip("src.zip", {"1.jpg": JPEG})
        pages = collect_archive_pages(source, self.work)
        with mock.patch("shutong.engine.kinds.manga.cbz.verify_cbz") as verify:
            write_cbz(pages, COMIC_INFO, self.target)
        verify.assert_not_called()

    def test_verify_reads_each_page_once_and_still_catches_a_bad_checksum(self):
        source = self._zip("src.zip", {"1.jpg": JPEG + b"x" * 64})
        pages = collect_archive_pages(source, self.work)
        write_cbz(pages, COMIC_INFO, self.target)
        with mock.patch.object(zipfile.ZipFile, "testzip", side_effect=AssertionError("second pass")):
            self.assertEqual(verify_cbz(self.target).page_count, 1)
        data = bytearray(self.target.read_bytes())
        offset = data.index(b"x" * 64)
        data[offset] = ord("y")
        self.target.write_bytes(bytes(data))
        with self.assertRaises(zipfile.BadZipFile):
            verify_cbz(self.target)

    def test_write_cbz_refuses_existing_target(self):
        source = self._zip("src.zip", {"01.jpg": JPEG})
        pages = collect_archive_pages(source, self.work)
        self.target.write_bytes(b"old")
        with self.assertRaises(FileExistsError):
            write_cbz(pages, COMIC_INFO, self.target)
        self.assertEqual(self.target.read_bytes(), b"old")

    def test_missing_bsdtar_is_build_error(self):
        library_patcher = mock.patch("shutong.engine.kinds.manga.cbz._USE_LIBARCHIVE", False)  # Windows reads differently
        library_patcher.start()
        self.addCleanup(library_patcher.stop)
        rar = self.root / "a.rar"
        rar.write_bytes(b"Rar!\x1a\x07\x00")
        with mock.patch("shutong.engine.kinds.manga.cbz.shutil.which", return_value=None):
            with self.assertRaisesRegex(BuildError, "bsdtar"):
                collect_archive_pages(rar, self.work)


if __name__ == "__main__":
    unittest.main()
