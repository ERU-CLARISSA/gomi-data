""".ics の RRULE/RDATE/EXDATE を python-dateutil（別の実装）で展開し、こちらの展開と一致するか確かめる。"""
import unittest
from datetime import date, datetime

from dateutil.rrule import rruleset, rrulestr

from gomi.ics import to_ics
from gomi.model import expand

REGION = {
    "id": "99999", "name": "テスト市",
    "categories": {"burnable": {"label": "燃えるごみ"}, "pet_bottle": {}, "metal": {}, "plastic": {}, "yard_waste": {}},
    "areas": [{"id": "1", "name": "A", "towns": [{"name": "A町"}], "schedules": [{
        "from": "2026-04-01", "to": "2027-03-31",
        "rules": [
            {"category": "burnable", "freq": "weekly", "byday": ["MO", "TH"]},
            {"category": "pet_bottle", "freq": "weekly", "byday": ["WE"], "interval": 2, "anchor": "2026-04-08"},
            {"category": "metal", "freq": "monthly", "byday": ["TU"], "nth": [1, 3], "nth_mode": "occurrence"},
            {"category": "plastic", "freq": "monthly", "byday": ["FR"], "nth": [2], "nth_mode": "week"},
            {"category": "yard_waste", "freq": "weekly", "byday": ["SA"], "from": "2026-05-01", "to": "2026-11-30"},
        ],
        "exceptions": [
            {"date": "2026-12-31", "cancel": ["*"]},
            {"date": "2027-01-04", "cancel": ["burnable"], "add": ["plastic"]},
            {"date": "2026-12-30", "add": ["burnable"]},
        ],
        "unknown": [{"from": "2027-02-01", "to": "2027-02-07", "reason": "テスト"}],
    }]}],
}


def ics_dates(text):
    """VEVENT ごとに dateutil で展開 → {日付: {種類の表示名}}。"""
    out = {}
    for block in text.split("BEGIN:VEVENT")[1:]:
        props = dict(line.split(":", 1) for line in block.split("END:VEVENT")[0].strip().split("\r\n"))
        start = datetime.strptime(props["DTSTART;VALUE=DATE"], "%Y%m%d")
        rs = rruleset()
        if "RRULE" in props:
            rs.rrule(rrulestr(props["RRULE"], dtstart=start))
        rs.rdate(start)
        for key, add in (("RDATE;VALUE=DATE", rs.rdate), ("EXDATE;VALUE=DATE", rs.exdate)):
            for v in props.get(key, "").split(","):
                if v:
                    add(datetime.strptime(v, "%Y%m%d"))
        label = props["SUMMARY"].replace("（いつもと違います）", "")
        for dt in rs:
            out.setdefault(dt.date(), set()).add(label)
    return out


class IcsTest(unittest.TestCase):
    def test_roundtrip(self):
        text = to_ics(REGION, "1")
        got = ics_dates(text)
        s = REGION["areas"][0]["schedules"][0]
        labels = {k: v.get("label", k) for k, v in REGION["categories"].items()}
        want = {d: {labels[c] for c in cats} for d, (cats, _) in expand(s, s["from"], s["to"]).items()}
        self.assertEqual(got, want)

    def test_rrule_text(self):
        text = to_ics(REGION, "1")
        self.assertIn("RRULE:FREQ=WEEKLY;INTERVAL=2;WKST=MO;BYDAY=WE;UNTIL=20270331", text)
        self.assertIn("RRULE:FREQ=MONTHLY;BYDAY=1TU,3TU;UNTIL=20270331", text)
        self.assertIn("EXDATE;VALUE=DATE:20261231", text)


if __name__ == "__main__":
    unittest.main()
