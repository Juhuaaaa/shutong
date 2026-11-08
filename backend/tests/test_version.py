from pathlib import Path
import json
import tomllib
import unittest

from shutong import __version__

ROOT = Path(__file__).resolve().parents[2]


class VersionTests(unittest.TestCase):
    def test_one_version_everywhere(self):
        """The app shows __version__; the packages it ships in must say the same."""
        pyproject = tomllib.loads((ROOT / "backend" / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(__version__, pyproject["project"]["version"])
        for package in ("desktop", "web"):
            with self.subTest(package=package):
                data = json.loads((ROOT / package / "package.json").read_text(encoding="utf-8"))
                self.assertEqual(data["version"], __version__)


if __name__ == "__main__":
    unittest.main()
