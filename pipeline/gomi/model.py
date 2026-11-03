"""共通形式（gomi-schedule/1）の収集日の展開。仕様は pipeline/SCHEMA.md。

アプリ（Dart）も同じ規則で展開するので、ここを変えたら SCHEMA.md と Dart 側もそろえる。
"""
from datetime import date, timedelta

WEEKDAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]  # date.weekday() の順
ALL = "*"


def parse_date(s):
    return s if isinstance(s, date) else date.fromisoformat(str(s))


def nth_of_month(d, mode="occurrence"):
    """第n の n。occurrence＝その月の n 回目の曜日、week＝日曜始まりのカレンダーで n 段目の週。"""
    if mode == "week":
        first = d.replace(day=1)
        offset = (first.weekday() + 1) % 7  # 1 日の前にある空きマス（日曜始まり）
        return (d.day - 1 + offset) // 7 + 1
    return (d.day - 1) // 7 + 1


def is_last_of_month(d):
    return (d + timedelta(days=7)).month != d.month


def _monday(d):
    return d - timedelta(days=d.weekday())


def rule_matches(rule, d):
    freq = rule["freq"]
    if (rule.get("from") and d < parse_date(rule["from"])) or (rule.get("to") and d > parse_date(rule["to"])):
        return False  # 季節限定の規則（例：剪定枝は 4〜12 月だけ）
    if freq == "dates":
        return d.isoformat() in rule["dates"]
    if WEEKDAYS[d.weekday()] not in rule["byday"]:
        return False
    if freq == "weekly":
        interval = rule.get("interval", 1)
        if interval == 1:
            return True
        weeks = (_monday(d) - _monday(parse_date(rule["anchor"]))).days // 7
        return weeks % interval == 0
    if freq == "monthly":
        nth = rule["nth"]
        return nth_of_month(d, rule.get("nth_mode", "occurrence")) in nth or (-1 in nth and is_last_of_month(d))
    raise ValueError(f"不明な freq: {freq}")


def in_schedule(schedule, d):
    if d < parse_date(schedule["from"]):
        return False
    if schedule.get("to") and d > parse_date(schedule["to"]):
        return False
    return not any(parse_date(u["from"]) <= d <= parse_date(u["to"]) for u in schedule.get("unknown", []))


def regular_categories(schedule, d):
    """例外日を当てる前の、規則だけで決まるカテゴリ（規則の順、重複なし）。"""
    out = []
    for r in schedule["rules"]:
        if r["category"] not in out and rule_matches(r, d):
            out.append(r["category"])
    return out


def exception_on(schedule, d):
    key = d.isoformat()
    return next((e for e in schedule.get("exceptions", []) if e["date"] == key), None)


def categories_on(schedule, d):
    """その日に収集されるカテゴリと、いつもと違う日かどうか。期間外・不明の日は ([], False)。"""
    if not in_schedule(schedule, d):
        return [], False
    cats = regular_categories(schedule, d)
    ex = exception_on(schedule, d)
    if ex is None:
        return cats, False
    cancel = ex.get("cancel", [])
    cats = [] if ALL in cancel else [c for c in cats if c not in cancel]
    cats += [c for c in ex.get("add", []) if c not in cats]
    return cats, True


def expand(schedule, start, end):
    """start〜end（両端を含む）の収集日 → {日付: (カテゴリ, いつもと違うか)}。"""
    out, d = {}, parse_date(start)
    end = parse_date(end)
    while d <= end:
        cats, changed = categories_on(schedule, d)
        if cats:
            out[d] = (cats, changed)
        d += timedelta(days=1)
    return out


def schedule_for(area, d):
    """その日を含む期間の schedule（期間は重ならない前提。validate で検査する）。"""
    d = parse_date(d)
    for s in area["schedules"]:
        if parse_date(s["from"]) <= d and (not s.get("to") or d <= parse_date(s["to"])):
            return s
    return None
