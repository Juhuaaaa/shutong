import re
import unittest

from .helpers import ApiCase


class OpenApiContractTests(ApiCase):
    def schema(self):
        return self.client.get("/api/openapi.json").json()

    def test_every_route_but_auth_requires_login(self):
        checked = 0
        for path, methods in self.schema()["paths"].items():
            if path.startswith("/api/auth/"):
                continue
            url = re.sub(r"\{[^}]+\}", "1", path)
            for method in methods:
                with self.subTest(method=method, path=path):
                    response = self.client.request(method.upper(), url, json={})
                    self.assertEqual(response.status_code, 401, response.text)
                    self.assertEqual(response.json(), {"detail": "未登录"})
                    checked += 1
        self.assertGreater(checked, 25)

    def test_every_route_documents_its_response(self):
        for path, methods in self.schema()["paths"].items():
            for method, operation in methods.items():
                with self.subTest(method=method, path=path):
                    self.assertIn("content", operation["responses"]["200"])


if __name__ == "__main__":
    unittest.main()
