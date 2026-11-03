import unittest
from datetime import date

from gomi.infer import infer_schedule
from gomi.model import categories_on, expand, nth_of_month


def sched(rules, exceptions=(), **kw):
    return {"from": "2026-04-01", "to": "2027-03-31", "rules": list(rules), "exceptions": list(exceptions), **kw}


class NthTest(unittest.TestCase):
    def test_occurrence_and_week(self):
        # 2026-08-01 は土曜。8/3（月）は 1 回目の月曜だが、日曜始まりのカレンダーでは第2週
        d = date(2026, 8, 3)
        self.assertEqual(nth_of_month(d, "occurrence"), 1)
        self.assertEqual(nth_of_month(d, "week"), 2)
        self.assertEqual(nth_of_month(date(2026, 8, 1), "week"), 1)

    def test_monthly_modes_differ(self):
        occ = sched([{"category": "metal", "freq": "monthly", "byday": ["MO"], "nth": [2], "nth_mode": "occurrence"}])
        week = sched([{"category": "metal", "freq": "monthly", "byday": ["MO"], "nth": [2], "nth_mode": "week"}])
        self.assertEqual(categories_on(occ, date(2026, 8, 10))[0], ["metal"])
        self.assertEqual(categories_on(week, date(2026, 8, 3))[0], ["metal"])
        self.assertEqual(categories_on(week, date(2026, 8, 10))[0], [])

    def test_last_week(self):
        s = sched([{"category": "metal", "freq": "monthly", "byday": ["FR"], "nth": [-1], "nth_mode": "occurrence"}])
        self.assertEqual(categories_on(s, date(2026, 7, 31))[0], ["metal"])
        self.assertEqual(categories_on(s, date(2026, 7, 24))[0], [])


class RuleTest(unittest.TestCase):
    def test_biweekly_anchor(self):
        s = sched([{"category": "pet_bottle", "freq": "weekly", "byday": ["TU"], "interval": 2, "anchor": "2026-04-07"}])
        got = [d for d in expand(s, "2026-04-01", "2026-05-10")]
        self.assertEqual(got, [date(2026, 4, 7), date(2026, 4, 21), date(2026, 5, 5)])

    def test_exceptions(self):
        s = sched([{"category": "burnable", "freq": "weekly", "byday": ["MO", "TH"]},
                   {"category": "plastic", "freq": "weekly", "byday": ["TH"]}],
                  [{"date": "2026-12-31", "cancel": ["*"]},
                   {"date": "2027-01-07", "cancel": ["plastic"]},
                   {"date": "2026-12-30", "add": ["burnable"], "note": "臨時収集"}])
        self.assertEqual(categories_on(s, date(2026, 12, 31)), ([], True))
        self.assertEqual(categories_on(s, date(2027, 1, 7)), (["burnable"], True))
        self.assertEqual(categories_on(s, date(2026, 12, 30)), (["burnable"], True))
        self.assertEqual(categories_on(s, date(2027, 1, 4)), (["burnable"], False))

    def test_unknown_and_out_of_period(self):
        s = sched([{"category": "burnable", "freq": "weekly", "byday": ["MO"]}],
                  unknown=[{"from": "2026-12-28", "to": "2027-01-04", "reason": "年末年始は未発表"}])
        self.assertEqual(categories_on(s, date(2026, 12, 28))[0], [])
        self.assertEqual(categories_on(s, date(2027, 4, 5))[0], [])
        self.assertEqual(categories_on(s, date(2027, 1, 11))[0], ["burnable"])

    def test_seasonal_rule(self):
        s = sched([{"category": "yard_waste", "freq": "weekly", "byday": ["MO"], "from": "2026-04-06", "to": "2026-12-28"}])
        self.assertEqual(categories_on(s, date(2026, 12, 28))[0], ["yard_waste"])
        self.assertEqual(categories_on(s, date(2027, 1, 4))[0], [])


class InferTest(unittest.TestCase):
    def test_weekly_with_holidays(self):
        s0 = sched([{"category": "burnable", "freq": "weekly", "byday": ["MO", "TH"]},
                    {"category": "metal", "freq": "monthly", "byday": ["WE"], "nth": [2, 4], "nth_mode": "occurrence"}],
                   [{"date": "2026-12-31", "cancel": ["*"]}, {"date": "2027-01-04", "cancel": ["*"]}])
        days = expand(s0, s0["from"], s0["to"])
        by_cat = {}
        for d, (cats, _) in days.items():
            for c in cats:
                by_cat.setdefault(c, []).append(d)
        s = infer_schedule(by_cat, s0["from"], s0["to"])
        self.assertIn({"category": "burnable", "freq": "weekly", "byday": ["MO", "TH"]}, s["rules"])
        self.assertIn({"category": "metal", "freq": "monthly", "byday": ["WE"], "nth": [2, 4], "nth_mode": "occurrence"}, s["rules"])
        self.assertEqual([e["date"] for e in s["exceptions"]], ["2026-12-31", "2027-01-04"])

    def test_irregular_falls_back_to_dates(self):
        dates = ["2026-04-08", "2026-05-13", "2026-06-10", "2026-07-08", "2026-08-05", "2026-10-07", "2026-11-04"]
        s = infer_schedule({"non_burnable": dates}, "2026-04-01", "2027-03-31")
        self.assertEqual(s["rules"][0]["freq"], "dates")


if __name__ == "__main__":
    unittest.main()
