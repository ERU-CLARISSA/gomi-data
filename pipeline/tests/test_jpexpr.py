import unittest
from datetime import date

from gomi.jpexpr import category_key, parse
from gomi.model import categories_on


def days(text, fy=2026, start=date(2026, 4, 1), end=date(2027, 3, 31)):
    s = {"from": start.isoformat(), "to": end.isoformat(), "rules": parse(text, "x", fy), "exceptions": []}
    out, d = [], start
    while d <= end:
        if categories_on(s, d)[0]:
            out.append(d)
        d = date.fromordinal(d.toordinal() + 1)
    return out


class ParseTest(unittest.TestCase):
    def test_weekly_forms(self):
        want = [{"category": "x", "freq": "weekly", "byday": ["MO", "TH"]}]
        for t in ["月 木", "月木", "月・木", "月曜\n木曜", "月曜日・木曜日", "毎週月曜 毎週木曜", "月、木", "月　木"]:
            self.assertEqual(parse(t, "x"), want, t)

    def test_nth_forms(self):
        want = [{"category": "x", "freq": "monthly", "byday": ["TU"], "nth": [1, 3], "nth_mode": "occurrence"}]
        for t in ["火1 火3", "火１　火３", "第1・第3 火", "第1・3火", "第1第3\n火曜", "第1・第3火曜日", "火1、火3"]:
            self.assertEqual(parse(t, "x"), want, t)

    def test_mixed_days_same_nth(self):
        r = parse("水2 金2", "x")
        self.assertEqual(r, [{"category": "x", "freq": "monthly", "byday": ["WE", "FR"], "nth": [2], "nth_mode": "occurrence"}])

    def test_month_ranges(self):
        # 金沢市の形：第5火曜は 4〜11 月と 2〜3 月だけ
        got = days("火5:4-11/2-3")
        self.assertIn(date(2026, 9, 29), got)
        self.assertNotIn(date(2026, 12, 29), got)
        self.assertIn(date(2027, 3, 30), got)
        self.assertEqual(days("水2:4-3"), days("水2"))

    def test_one_month_different(self):
        # 生駒市：「第1・3金※１月は第３・第５」
        got = days("第1・3金※１月は第３・第５")
        self.assertIn(date(2026, 4, 3), got)
        self.assertNotIn(date(2027, 1, 1), got)
        self.assertIn(date(2027, 1, 15), got)
        self.assertIn(date(2027, 1, 29), got)
        # 津幡町：「金３（1　金4）」＝ 1 月だけ第4金
        got = days("金３（1　金4）")
        self.assertIn(date(2026, 4, 17), got)
        self.assertNotIn(date(2027, 1, 15), got)
        self.assertIn(date(2027, 1, 22), got)

    def test_dates(self):
        r = parse("20260413 20260518", "x")
        self.assertEqual(r, [{"category": "x", "freq": "dates", "dates": ["2026-04-13", "2026-05-18"]}])

    def test_rules_plus_dates(self):
        r = parse("金1 金3 20261229", "x")
        self.assertEqual(r[-1], {"category": "x", "freq": "dates", "dates": ["2026-12-29"]})
        self.assertEqual(r[0]["nth"], [1, 3])

    def test_empty_and_unknown(self):
        self.assertEqual(parse("", "x"), [])
        self.assertEqual(parse("-", "x"), [])
        with self.assertRaises(ValueError):
            parse("従来どおり", "x")

    def test_category_key(self):
        for label, key in [("燃えるごみ", "burnable"), ("可燃物", "burnable"), ("不燃・ビン・粗大・ペットボトル", "oversized"),
                           ("燃やせないごみ", "non_burnable"), ("ﾌﾟﾗｽﾁｯｸ製容器包装", "plastic"), ("缶・びん", "recyclables"),
                           ("古紙・布類", "paper_cloth"), ("蛍光管等", "hazardous"), ("剪定枝", "yard_waste"),
                           ("ペットボトル", "pet_bottle"), ("あきびん", "glass_bottle")]:
            self.assertEqual(category_key(label), key, label)


if __name__ == "__main__":
    unittest.main()
