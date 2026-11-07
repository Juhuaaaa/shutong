import unittest

from .helpers import ApiCase


class ServerRoutesTests(ApiCase):
    def setUp(self):
        super().setUp()
        self.login()

    def test_crud_hides_the_password(self):
        server = self.make_server()
        self.assertEqual(server["password"], "已设置")
        self.assertNotIn("s3cret-pw", self.client.get("/api/servers").text)
        kept = self.client.patch("/api/servers/{0}".format(server["id"]),
                                 json={"password": "已设置", "username": "other"}).json()
        self.assertEqual((kept["username"], kept["password"]), ("other", "已设置"))
        from shutong.store.servers import ServerStore

        self.assertEqual(ServerStore(self.app.state.db).get(server["id"]).password, "s3cret-pw")
        again = self.client.post("/api/servers", json={"kind": "kavita", "name": "家里", "base_url": "http://x"})
        self.assertEqual((again.status_code, again.json()["detail"]), (409, "媒体服务器名已存在"))
        bad = self.client.post("/api/servers", json={"kind": "kavita", "name": "x", "base_url": "kavita:5000"})
        self.assertEqual(bad.status_code, 422)
        self.assertEqual(self.client.delete("/api/servers/{0}".format(server["id"])).status_code, 200)
        self.assertEqual(self.client.get("/api/servers").json(), [])
        self.assertEqual(self.client.patch("/api/servers/99", json={"name": "x"}).status_code, 404)

    def test_connection_test(self):
        server = self.make_server()
        result = self.client.post("/api/servers/{0}/test".format(server["id"])).json()
        self.assertEqual((result["ok"], [entry["id"] for entry in result["libraries"]]), (True, [3, 7]))
        self.server_error = "Kavita 用户名或密码错误"
        failed = self.client.post("/api/servers/{0}/test".format(server["id"]))
        self.assertEqual((failed.status_code, failed.json()["ok"], failed.json()["error"]),
                         (200, False, "Kavita 用户名或密码错误"))
        self.assertNotIn("s3cret-pw", failed.text)

    def test_library_mapping(self):
        server = self.make_server()
        library = self.make_library()
        mapped = self.client.patch("/api/libraries/{0}".format(library["id"]),
                                   json={"server_id": server["id"], "server_library_id": 3}).json()
        self.assertEqual((mapped["server_id"], mapped["server_library_id"]), (server["id"], 3))
        missing = self.client.patch("/api/libraries/{0}".format(library["id"]), json={"server_id": 99})
        self.assertEqual((missing.status_code, missing.json()["detail"]), (422, "媒体服务器不存在"))
        self.client.delete("/api/servers/{0}".format(server["id"]))
        cleared = self.client.get("/api/libraries/{0}".format(library["id"])).json()
        self.assertEqual((cleared["server_id"], cleared["server_library_id"]), (None, None))
        unmapped = self.client.patch("/api/libraries/{0}".format(library["id"]),
                                     json={"server_id": None}).json()
        self.assertIsNone(unmapped["server_id"])


if __name__ == "__main__":
    unittest.main()
