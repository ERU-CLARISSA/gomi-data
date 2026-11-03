"""共通形式 → iCalendar（.ics）。規則は RRULE、休みは EXDATE、臨時の収集は単発の予定にする。

第n の数え方が week のもの、日付の一覧は RRULE で書けないので RDATE で並べる。
"""
from datetime import timedelta

from .model import ALL, exception_on, parse_date, rule_matches

SEARCH_DAYS = 800  # 最初の収集日を探す範囲


def _d(d):
    return d.strftime("%Y%m%d")


def _bounds(schedule, rule):
    start = max(parse_date(schedule["from"]), parse_date(rule["from"]) if rule.get("from") else parse_date(schedule["from"]))
    ends = [parse_date(x) for x in (schedule.get("to"), rule.get("to")) if x]
    return start, min(ends) if ends else None


def _occurrences(rule, start, end, limit=SEARCH_DAYS):
    d, last = start, end or start + timedelta(days=limit)
    while d <= last:
        if rule_matches(rule, d):
            yield d
        d += timedelta(days=1)


def _rrule(rule, until):
    if rule["freq"] == "weekly":
        parts = ["FREQ=WEEKLY", "WKST=MO", "BYDAY=" + ",".join(rule["byday"])]
        if rule.get("interval", 1) != 1:
            parts.insert(1, f"INTERVAL={rule['interval']}")
    elif rule["freq"] == "monthly" and rule.get("nth_mode") == "occurrence":
        parts = ["FREQ=MONTHLY", "BYDAY=" + ",".join(f"{n}{d}" for d in rule["byday"] for n in rule["nth"])]
    else:
        return None
    if until:
        parts.append(f"UNTIL={_d(until)}")
    return ";".join(parts)


def _skipped(schedule, rule, d):
    """規則に当たるが、例外日や不明期間で消える日か。"""
    if any(parse_date(u["from"]) <= d <= parse_date(u["to"]) for u in schedule.get("unknown", [])):
        return True
    ex = exception_on(schedule, d)
    if not ex:
        return False
    cancel = ex.get("cancel", [])
    return (ALL in cancel or rule["category"] in cancel) and rule["category"] not in ex.get("add", [])


def area_events(region, area):
    """1 地区の VEVENT のリスト（文字列）。"""
    labels = {k: v.get("label") or k for k, v in region["categories"].items()}
    events = []
    for si, s in enumerate(area["schedules"]):
        for ri, rule in enumerate(s["rules"]):
            start, end = _bounds(s, rule)
            first = next(_occurrences(rule, start, end), None)
            if first is None:
                continue
            lines = [f"UID:{region['id']}-{area['id']}-{si}-{ri}@gomi-app", f"DTSTART;VALUE=DATE:{_d(first)}",
                     f"SUMMARY:{labels.get(rule['category'], rule['category'])}"]
            rr = _rrule(rule, end)
            if rr:
                lines.append(f"RRULE:{rr}")
                # 例外日と不明期間に当たる日を EXDATE に（どちらも期間の中にしかない）
                check = [parse_date(e["date"]) for e in s.get("exceptions", [])]
                for u in s.get("unknown", []):
                    check += list(_occurrences(rule, parse_date(u["from"]), parse_date(u["to"])))
                exdates = sorted({d for d in check if d >= first and (end is None or d <= end)
                                  and rule_matches(rule, d) and _skipped(s, rule, d)})
            else:
                dates = [d for d in _occurrences(rule, start, end) if not _skipped(s, rule, d)]
                if not dates:
                    continue
                lines[1] = f"DTSTART;VALUE=DATE:{_d(dates[0])}"
                if dates[1:]:
                    lines.append("RDATE;VALUE=DATE:" + ",".join(map(_d, dates[1:])))
                exdates = []
            if exdates:
                lines.append("EXDATE;VALUE=DATE:" + ",".join(map(_d, exdates)))
            events.append(lines)
        for e in s.get("exceptions", []):
            for cat in e.get("add", []):
                d = parse_date(e["date"])
                events.append([f"UID:{region['id']}-{area['id']}-{si}-{e['date']}-{cat}@gomi-app",
                               f"DTSTART;VALUE=DATE:{_d(d)}",
                               f"SUMMARY:{labels.get(cat, cat)}（いつもと違います）"])
    return events


def to_ics(region, area_id):
    area = next(a for a in region["areas"] if a["id"] == area_id)
    out = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//ERU CLARISSA//gomi-app//JA", "CALSCALE:GREGORIAN",
           f"X-WR-CALNAME:{region['name']} {area['name']}"]
    for ev in area_events(region, area):
        out += ["BEGIN:VEVENT", *ev, "END:VEVENT"]
    out.append("END:VCALENDAR")
    return "\r\n".join(out) + "\r\n"
