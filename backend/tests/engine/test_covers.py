import io
from pathlib import Path
import tempfile
import unittest
import zipfile

from PIL import Image

from shutong.engine import covers
from shutong.engine.kinds.manga.cbz import verify_cbz

def jpeg(image):
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=95)
    return buffer.getvalue()


def page(colour=(90, 90, 90), size=(272, 400)):
    return jpeg(Image.new("RGB", size, colour))


def jacket(height=400, ratio=0.68, spine=0.08, flap=0.3):
    """flap | front | spine | back | flap, each a flat colour."""
    widths = [flap, ratio, spine, ratio, flap]
    colours = [(200, 200, 200), (220, 40, 40), (20, 20, 120), (40, 160, 40), (200, 200, 200)]
    image = Image.new("RGB", (int(sum(widths) * height), height), "white")
    x = 0
    for width, colour in zip(widths, colours):
        image.paste(colour, (x, 0, x + int(width * height), height))
        x += int(width * height)
    left = int(flap * height)
    return image, (left, left + int(ratio * height))


COMIC_INFO = b"<?xml version='1.0'?><ComicInfo><Series>a</Series><PageCount>4</PageCount></ComicInfo>"


class CoverCase(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.root = Path(self._directory.name)

    def cbz(self, first=None, name="Vol.01.cbz"):
        path = self.root / name
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("001.jpg", first or page((10, 10, 10)))
            for number in range(2, 5):
                archive.writestr("{0:03d}.jpg".format(number), page((number * 20,) * 3))
            archive.writestr("ComicInfo.xml", COMIC_INFO)
        return path


class JacketTests(CoverCase):
    def test_finds_the_front_of_a_jacket(self):
        image, (left, right) = jacket()
        found = covers.find_jacket(self.cbz(jpeg(image)))
        self.assertEqual(found.page, "001.jpg")
        self.assertLessEqual(abs(found.left * image.width - left), 6)
        self.assertLessEqual(abs(found.right * image.width - right), 6)

    def test_an_ordinary_first_page_is_no_jacket(self):
        self.assertIsNone(covers.find_jacket(self.cbz()))

    def test_a_long_strip_is_no_jacket(self):
        self.assertIsNone(covers.find_jacket(self.cbz(page(size=(1600, 400)))))

    def test_crop_keeps_the_given_part(self):
        image, (left, right) = jacket()
        cropped = covers.crop_image(jpeg(image), left / image.width, right / image.width)
        with Image.open(io.BytesIO(cropped)) as result:
            self.assertLessEqual(abs(result.width - (right - left)), 2)
            red, green, blue = result.convert("RGB").getpixel((result.width // 2, result.height // 2))
        self.assertGreater(red, 180)
        self.assertLess(green, 80)

    def test_a_bad_crop_is_refused(self):
        with self.assertRaises(ValueError):
            covers.crop_image(page(), 0.8, 0.2)
        with self.assertRaises(ValueError):
            covers.crop_image(page(), -0.1, 0.5)


class CbzCoverTests(CoverCase):
    def test_a_chosen_page_goes_in_front_and_nothing_else_changes(self):
        path = self.cbz()
        with zipfile.ZipFile(path) as archive:
            before = {info.filename: info.CRC for info in archive.infolist() if info.filename != "ComicInfo.xml"}
        covers.set_cover(path, "003.jpg")
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            self.assertEqual(sorted(names)[0], "000.jpg")
            self.assertEqual(archive.read("000.jpg"), archive.read("003.jpg"))
            self.assertIn(b"<PageCount>5</PageCount>", archive.read("ComicInfo.xml"))
            for name, crc in before.items():
                self.assertEqual(archive.getinfo(name).CRC, crc)
        verify_cbz(path)
        self.assertEqual(covers.cover_options(path).pages[0], "001.jpg")
        self.assertTrue(covers.cover_options(path).added)

    def test_a_new_cover_replaces_the_added_one(self):
        path = self.cbz()
        covers.set_cover(path, "003.jpg")
        covers.set_cover(path, "004.jpg")
        with zipfile.ZipFile(path) as archive:
            self.assertEqual(archive.read("000.jpg"), archive.read("004.jpg"))
            self.assertEqual(sum(name.startswith("000") for name in archive.namelist()), 1)
            self.assertIn(b"<PageCount>5</PageCount>", archive.read("ComicInfo.xml"))

    def test_the_first_page_means_back_to_the_original(self):
        path = self.cbz()
        covers.set_cover(path, "003.jpg")
        covers.set_cover(path, "001.jpg")
        with zipfile.ZipFile(path) as archive:
            self.assertNotIn("000.jpg", archive.namelist())
            self.assertIn(b"<PageCount>4</PageCount>", archive.read("ComicInfo.xml"))
        self.assertFalse(covers.cover_options(path).added)

    def test_a_crop_is_stored_as_a_jpeg_page(self):
        image, (left, right) = jacket()
        path = self.cbz(jpeg(image))
        covers.set_cover(path, "001.jpg", left / image.width, right / image.width)
        with zipfile.ZipFile(path) as archive:
            with Image.open(io.BytesIO(archive.read("000.jpg"))) as cover:
                self.assertLess(cover.width, image.width // 2)
        verify_cbz(path)

    def test_an_unknown_page_is_refused_and_the_file_stays(self):
        path = self.cbz()
        before = path.read_bytes()
        for name in ("999.jpg", "../../etc/passwd", "ComicInfo.xml"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                covers.set_cover(path, name)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual([entry.name for entry in self.root.iterdir()], [path.name])

    def test_a_png_page_stays_a_png(self):
        buffer = io.BytesIO()
        Image.new("RGB", (272, 400), (1, 2, 3)).save(buffer, format="PNG")
        path = self.root / "p.cbz"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("001.jpg", page())
            archive.writestr("002.png", buffer.getvalue())
            archive.writestr("ComicInfo.xml", COMIC_INFO)
        covers.set_cover(path, "002.png")
        with zipfile.ZipFile(path) as archive:
            self.assertIn("000.png", archive.namelist())
        verify_cbz(path)

    def test_an_archive_of_other_names_gets_the_name_kavita_prefers(self):
        path = self.root / "old.cbz"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("Vol01/a.jpg", page((1, 1, 1)))
            archive.writestr("Vol01/b.jpg", page((2, 2, 2)))
            archive.writestr("ComicInfo.xml", COMIC_INFO)
        covers.set_cover(path, "Vol01/b.jpg")
        with zipfile.ZipFile(path) as archive:
            self.assertIn("!cover.jpg", archive.namelist())
        self.assertEqual(covers.cover_options(path).pages, ("Vol01/a.jpg", "Vol01/b.jpg"))

    def test_the_current_cover_can_be_read(self):
        path = self.cbz()
        self.assertEqual(covers.read_cover(path), covers.read_page(path, "001.jpg"))
        covers.set_cover(path, "003.jpg")
        self.assertEqual(covers.read_cover(path), covers.read_page(path, "003.jpg"))


class ThumbnailTests(CoverCase):
    def test_a_thumbnail_is_small_and_a_jpeg(self):
        data = covers.thumbnail(page(size=(1400, 2000)), 200)
        with Image.open(io.BytesIO(data)) as image:
            self.assertEqual((image.format, image.width), ("JPEG", 200))

    def test_not_an_image_is_an_error(self):
        with self.assertRaises(ValueError):
            covers.thumbnail(b"nope", 200)
