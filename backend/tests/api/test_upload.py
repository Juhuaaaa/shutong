import io
from pathlib import Path
import shutil
import unittest
import zipfile

from .helpers import JPEG, ApiCase


def archive(name):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as handle:
        handle.writestr("01.jpg", JPEG + name.encode())
    return buffer.getvalue()


class UploadTests(ApiCase):
    def setUp(self):
        super().setUp()
        self.login()
        self.library = self.make_library()
        self.source_root = self.root / "source"

    def upload(self, *files):
        return self.client.post("/api/libraries/{0}/upload".format(self.library["id"]),
                                files=[("files", (name, data, "application/zip")) for name, data in files])

    def test_files_land_by_relative_path(self):
        response = self.upload(("迷宫饭/迷宫饭 Vol.01.zip", archive("1")), ("x.zip", archive("x")))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual([entry["path"] for entry in response.json()["saved"]], ["迷宫饭/迷宫饭 Vol.01.zip", "x.zip"])
        self.assertTrue((self.source_root / "迷宫饭" / "迷宫饭 Vol.01.zip").is_file())
        self.assertEqual(sorted(path.name for path in self.source_root.rglob("*.part")), [])
        self.client.post("/api/libraries/{0}/scan".format(self.library["id"]))
        found = self.client.get("/api/items", params={"library_id": self.library["id"], "q": "迷宫饭"}).json()
        self.assertEqual(found["items"][0]["status"], "published", found["items"][0])

    def test_same_name_never_overwrites(self):
        self.upload(("迷宫饭/Vol.01.zip", archive("first")))
        original = (self.source_root / "迷宫饭" / "Vol.01.zip").read_bytes()
        response = self.upload(("迷宫饭/Vol.01.zip", archive("second")))
        self.assertEqual(response.json()["saved"][0]["path"], "迷宫饭/Vol.01-1.zip")
        self.assertEqual((self.source_root / "迷宫饭" / "Vol.01.zip").read_bytes(), original)
        self.assertEqual(self.upload(("迷宫饭/Vol.01.zip", b"3")).json()["saved"][0]["path"], "迷宫饭/Vol.01-2.zip")

    def test_paths_that_escape_are_rejected(self):
        before = sorted(path.name for path in self.root.iterdir())
        for name in ("../x.zip", "/etc/x.zip", "a/../../x.zip", ".shutong/trash/x.zip", "a\\..\\..\\x.zip",
                     ""):
            with self.subTest(name=name):
                response = self.upload((name, b"data"))
                self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(sorted(path.name for path in self.root.iterdir()), before)
        self.assertEqual(list(self.source_root.iterdir()), [])

    def test_symlinked_folder_cannot_lead_outside(self):
        outside = self.root / "outside"
        outside.mkdir()
        (self.source_root / "link").symlink_to(outside, target_is_directory=True)
        response = self.upload(("link/x.zip", b"data"))
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(list(outside.iterdir()), [])

    def test_state_folder_check_ignores_case(self):
        for name in (".Shutong/trash/x.zip", ".SHUTONG/x.zip"):
            with self.subTest(name=name):
                self.assertEqual(self.upload((name, b"data")).status_code, 422)
        self.assertEqual(list(self.source_root.iterdir()), [])

    def test_hidden_files_are_skipped(self):
        response = self.upload(("迷宫饭/.DS_Store", b"junk"), ("迷宫饭/Vol.01.zip", archive("1")))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(([entry["path"] for entry in response.json()["saved"]], response.json()["skipped"]),
                         (["迷宫饭/Vol.01.zip"], ["迷宫饭/.DS_Store"]))
        self.assertFalse((self.source_root / "迷宫饭" / ".DS_Store").exists())

    def test_longest_allowed_name_uploads(self):
        name = "长" * 83 + ".zip"  # 253 bytes in UTF-8: fits, but not with ".part" appended
        response = self.upload(("迷宫饭/" + name, b"data"))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue((self.source_root / "迷宫饭" / name).exists())
        self.assertEqual([path.name for path in (self.source_root / "迷宫饭").iterdir()], [name])

    def test_temporary_name_is_short_and_hidden(self):
        from unittest import mock

        import shutong.api.upload as upload_module

        seen = []
        real = upload_module.shutil.copyfileobj

        def spy(source, handle, *args):
            seen.append(Path(handle.name).name)
            return real(source, handle, *args)

        with mock.patch.object(upload_module.shutil, "copyfileobj", spy):
            self.upload(("迷宫饭/" + "长" * 83 + ".zip", b"data"))
        self.assertEqual(len(seen), 1)
        self.assertTrue(seen[0].startswith(".upload-") and len(seen[0].encode()) < 64, seen[0])

    def test_missing_source_directory(self):
        shutil.rmtree(self.source_root)
        response = self.upload(("x.zip", b"data"))
        self.assertEqual((response.status_code, response.json()["detail"]), (409, "库目录不可用"))


if __name__ == "__main__":
    unittest.main()
