from pathlib import Path
import tempfile
import unittest
from unittest import mock

from PIL import Image
from pypdf import PdfReader, PdfWriter

from shutong.engine.kinds.base import BuildError
from shutong.engine.kinds.manga import pdf as pdf_module
from shutong.engine.kinds.manga.pdf import collect_pdf_pages, pdf_page_count


class PdfPagesTests(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.root = Path(self._directory.name)
        self.work = self.root / "work"
        self.work.mkdir()

    def _image_pdf(self, name, images):
        path = self.root / name
        images[0].save(path, "PDF", save_all=True, append_images=images[1:], resolution=72)
        return path

    def _with_blank_page(self, source, name, index):
        reader = PdfReader(str(source))
        writer = PdfWriter()
        for number, page in enumerate(reader.pages):
            if number == index:
                writer.add_blank_page(width=page.mediabox.width, height=page.mediabox.height)
            writer.add_page(page)
        path = self.root / name
        with open(path, "wb") as handle:
            writer.write(handle)
        return path

    def test_extracts_one_page_per_pdf_page(self):
        source = self._image_pdf("a.pdf", [Image.new("RGB", (60, 90), "red"),
                                           Image.new("1", (60, 90), 1)])
        pages = collect_pdf_pages(source, self.work)
        self.assertEqual([page.extension for page in pages], [".jpg", ".png"])
        for page in pages:
            self.assertTrue(page.path.is_file())
            self.assertEqual(page.path.parent, self.work)

    def test_blank_page_filled_with_common_size(self):
        base = self._image_pdf("b.pdf", [Image.new("RGB", (60, 90), "red"),
                                         Image.new("RGB", (60, 90), "blue")])
        source = self._with_blank_page(base, "c.pdf", 1)
        pages = collect_pdf_pages(source, self.work)
        self.assertEqual(len(pages), 3)
        with Image.open(pages[1].path) as blank, Image.open(pages[0].path) as first:
            self.assertEqual(blank.size, first.size)
            self.assertEqual(blank.mode, "1")

    def test_pdf_without_images_fails(self):
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=300)
        writer.add_blank_page(width=200, height=300)
        source = self.root / "blank.pdf"
        with open(source, "wb") as handle:
            writer.write(handle)
        with self.assertRaisesRegex(BuildError, "no embedded page images"):
            collect_pdf_pages(source, self.work)

    def test_unreadable_pdf_fails(self):
        source = self.root / "not.pdf"
        source.write_bytes(b"this is not a pdf")
        with self.assertRaises(BuildError):
            collect_pdf_pages(source, self.work)

    def test_pages_are_written_as_they_are_encoded(self):
        # Holding a whole scanned volume in memory OOMs small NAS boxes; each page must
        # already be on disk before the next one is encoded.
        source = self._image_pdf("big.pdf", [Image.new("RGB", (60, 90), c) for c in ("red", "blue", "green")])
        real_encode = pdf_module._encode
        seen = []

        def encode(*args):
            seen.append(len(list(self.work.iterdir())))
            return real_encode(*args)

        with mock.patch.object(pdf_module, "_encode", side_effect=encode):
            collect_pdf_pages(source, self.work)
        self.assertEqual(seen, [0, 1, 2])

    def test_unexpected_reader_errors_become_build_error(self):
        source = self._image_pdf("a.pdf", [Image.new("RGB", (60, 90), "red")])
        for error in (KeyError("/Root"), TypeError("bad"), AttributeError("x")):
            with self.subTest(error=type(error).__name__), \
                    mock.patch.object(pdf_module, "PdfReader", side_effect=error):
                with self.assertRaises(BuildError):
                    collect_pdf_pages(source, self.work)
                with self.assertRaises(BuildError):
                    pdf_page_count(source)

    def test_encode_failure_becomes_build_error(self):
        source = self._image_pdf("a.pdf", [Image.new("RGB", (60, 90), "red")])
        with mock.patch.object(pdf_module, "_encode", side_effect=ValueError("mode I;16")):
            with self.assertRaises(BuildError):
                collect_pdf_pages(source, self.work)

    def test_jpeg_pages_are_copied_without_reencoding(self):
        # Decoding a JPEG and saving it again costs time and quality; the PDF already holds the file.
        source = self._image_pdf("j.pdf", [Image.new("RGB", (60, 90), "red"), Image.new("L", (60, 90), 128)])
        embedded = [next(iter(page.images)).data for page in PdfReader(str(source)).pages]
        self.assertTrue(all(data.startswith(b"\xff\xd8") for data in embedded))
        pages = collect_pdf_pages(source, self.work)
        self.assertEqual([page.extension for page in pages], [".jpg", ".jpg"])
        self.assertEqual([page.path.read_bytes() for page in pages], embedded)

    def test_png_pages_skip_the_slow_optimize_pass(self):
        # optimize=True took ~6x as long on a 54-megapixel scan for a 3% smaller page.
        image = Image.new("1", (60, 90), 1)
        with mock.patch.object(Image.Image, "save", autospec=True) as save:
            pdf_module._encode(image)
        self.assertNotIn("optimize", save.call_args.kwargs)

    def test_owner_password_only_pdf_is_readable(self):
        base = self._image_pdf("plain.pdf", [Image.new("RGB", (60, 90), "red")])
        writer = PdfWriter(clone_from=str(base))
        writer.encrypt(user_password="", owner_password="owner-secret")
        locked = self.root / "locked.pdf"
        with open(locked, "wb") as handle:
            writer.write(handle)
        self.assertTrue(PdfReader(str(locked)).is_encrypted)
        self.assertEqual(len(collect_pdf_pages(locked, self.work)), 1)
        self.assertEqual(pdf_page_count(locked), 1)


if __name__ == "__main__":
    unittest.main()
