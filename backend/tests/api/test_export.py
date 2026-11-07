import json
import subprocess
import sys
import unittest
from pathlib import Path


class ExportTests(unittest.TestCase):
    def test_export_prints_the_openapi_schema(self):
        output = subprocess.run([sys.executable, "-m", "shutong.api.export"], capture_output=True, text=True,
                                cwd=Path(__file__).resolve().parents[2], check=True).stdout
        schema = json.loads(output)
        self.assertIn("/api/items", schema["paths"])
        self.assertEqual(output, json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    unittest.main()
