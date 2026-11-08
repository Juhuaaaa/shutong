"""Browsing the server's folders, for choosing library folders where no folder dialog exists (a server's page)."""
from .helpers import ApiCase


class FolderRoutesTests(ApiCase):
    def setUp(self):
        super().setUp()
        self.login()
        for name in ("下载/漫画", "下载/轻小说", "书库", ".hidden"):
            (self.root / "nas" / name).mkdir(parents=True)
        (self.root / "nas" / "readme.txt").write_text("x")

    def folders(self, path):
        return self.client.get("/api/folders", params={"path": str(path)})

    def test_lists_the_folders_in_a_folder(self):
        body = self.folders(self.root / "nas").json()
        self.assertEqual(body["path"], str(self.root / "nas"))
        self.assertEqual(body["parent"], str(self.root))
        self.assertEqual(body["folders"], ["下载", "书库"])  # no files, no hidden folders

    def test_the_root_has_no_parent(self):
        self.assertIsNone(self.folders("/").json()["parent"])

    def test_refuses_what_is_not_a_folder(self):
        self.assertEqual(self.folders(self.root / "nas" / "missing").status_code, 404)
        self.assertEqual(self.folders(self.root / "nas" / "readme.txt").status_code, 422)
        self.assertEqual(self.folders("relative/path").status_code, 422)

    def test_needs_login(self):
        self.client.post("/api/auth/logout")
        self.assertEqual(self.folders(self.root).status_code, 401)
