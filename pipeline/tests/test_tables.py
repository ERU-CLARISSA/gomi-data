import unittest

from gomi.sources.tables import Categories


class CategoriesTest(unittest.TestCase):
    def test_same_base_gets_new_key(self):
        c = Categories()
        self.assertEqual(c.key("資源ごみ"), "recyclables")
        self.assertEqual(c.key("缶・びん"), "recyclables_2")
        self.assertEqual(c.info["recyclables_2"], {"label": "缶・びん", "base": "recyclables"})
        self.assertEqual(c.key("資源ごみ"), "recyclables")  # 同じ名前は同じキー

    def test_override(self):
        c = Categories({"資源回収(29~31日は容プラのみ)": "recyclables"})
        self.assertEqual(c.key("資源回収（29～31 日は容プラのみ）"), "recyclables")


if __name__ == "__main__":
    unittest.main()
