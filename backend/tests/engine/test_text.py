import unittest

from shutong.engine.text import is_safe_path_component, normalize_title


class TextTests(unittest.TestCase):
    def test_normalizes_traditional_title_but_preserves_english(self):
        self.assertEqual(normalize_title("魔女與使魔"), "魔女与使魔")
        self.assertEqual(normalize_title("To LOVEる"), "To LOVEる")

    def test_safe_path_component(self):
        self.assertTrue(is_safe_path_component("间谍过家家[bili电子版]"))
        for value in ("", " ", ".", "..", "a/b", "a\\b", "a\x00b", None):
            with self.subTest(value=value):
                self.assertFalse(is_safe_path_component(value))


if __name__ == "__main__":
    unittest.main()
