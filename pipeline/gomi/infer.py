"""日付入りのカレンダー（実際の収集日の一覧）から、規則＋例外日を推定する。

曜日ごとに「毎週／第n（2通りの数え方）／隔週・4週ごと／規則なし」を試し、例外日が一番少ないものを選ぶ。
例外日が多すぎるときは規則にせず、日付の一覧（freq=dates）で持つ。最後に展開し直して元の日付と一致するか確かめる。
"""
from collections import defaultdict
from datetime import timedelta

from .model import WEEKDAYS, expand, nth_of_month, parse_date, rule_matches

MAX_EXCEPTION_RATE = 0.15  # 曜日ごとの例外日がこの割合を超えたら規則にしない


def _days(start, end):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def _candidates(wd, actual, start, end):
    """曜日 wd の収集日 actual に対する規則の候補（簡単な順）。"""
    yield {"freq": "weekly", "byday": [wd]}
    first, last = min(actual), max(actual)
    if (first - start).days > 31 or (end - last).days > 31:  # 1 か月以上の空きがある＝季節限定
        yield {"freq": "weekly", "byday": [wd], "from": first.isoformat(), "to": last.isoformat()}
    days = [d for d in _days(start, end) if WEEKDAYS[d.weekday()] == wd]
    for mode in ("occurrence", "week"):
        nth = sorted({nth_of_month(d, mode) for d in actual})
        # その n の日のうち半分以上で収集がある n だけ残す
        nth = [n for n in nth
               if sum(1 for d in actual if nth_of_month(d, mode) == n)
               >= 0.5 * sum(1 for d in days if nth_of_month(d, mode) == n)]
        if nth and len(nth) < 5:
            yield {"freq": "monthly", "byday": [wd], "nth": nth, "nth_mode": mode}
    for interval in (2, 4):
        for anchor in sorted(actual)[:interval]:  # 最初の数回の休みに引きずられないよう、起点を何通りか試す
            yield {"freq": "weekly", "byday": [wd], "interval": interval, "anchor": anchor.isoformat()}


def _expected(rule, start, end):
    return {d for d in _days(start, end) if rule_matches(rule, d)}


def infer_category(dates, start, end):
    """1 種類の収集日 → (rules, cancels, adds)。cancels/adds は日付の集合。"""
    start, end = parse_date(start), parse_date(end)
    by_wd = defaultdict(set)
    for d in map(parse_date, dates):
        by_wd[WEEKDAYS[d.weekday()]].add(d)
    rules, cancels, adds, loose = [], set(), set(), set()
    for wd, actual in by_wd.items():
        best = None
        for rule in _candidates(wd, actual, start, end):
            exp = _expected(rule, start, end)
            cost = len(exp - actual) + len(actual - exp)
            if best is None or cost < best[0]:
                best = (cost, rule, exp)
        cost, rule, exp = best
        if cost <= MAX_EXCEPTION_RATE * len(actual):
            rules.append(rule)
            cancels |= exp - actual
            adds |= actual - exp
        else:
            loose |= actual
    rules = _merge(rules)
    if loose:
        rules.append({"freq": "dates", "dates": sorted(d.isoformat() for d in loose)})
    return rules, cancels, adds


def _merge(rules):
    """byday 以外が同じ規則をまとめる（毎週 月 ＋ 毎週 木 → 毎週 月・木）。"""
    merged = {}
    for r in rules:
        key = tuple(sorted((k, str(v)) for k, v in r.items() if k != "byday"))
        if key in merged:
            merged[key]["byday"] += r["byday"]
        else:
            merged[key] = {**r, "byday": list(r["byday"])}
    for r in merged.values():
        r["byday"].sort(key=WEEKDAYS.index)
    return list(merged.values())


def infer_schedule(dates_by_category, start, end):
    """{種類: [日付…]} → schedule（from/to/rules/exceptions）。展開し直して元と一致しなければ例外を出す。"""
    rules, ex = [], defaultdict(lambda: {"cancel": [], "add": []})
    for cat, dates in dates_by_category.items():
        r, cancels, adds = infer_category(dates, start, end)
        rules += [{"category": cat, **x} for x in r]
        for d in cancels:
            ex[d]["cancel"].append(cat)
        for d in adds:
            ex[d]["add"].append(cat)
    exceptions = []
    for d in sorted(ex):
        e = {"date": d.isoformat()}
        e.update({k: v for k, v in ex[d].items() if v})
        exceptions.append(e)
    schedule = {"from": parse_date(start).isoformat(), "to": parse_date(end).isoformat(),
                "rules": rules, "exceptions": exceptions}
    verify(schedule, dates_by_category)
    return schedule


def verify(schedule, dates_by_category):
    got = defaultdict(set)
    for d, (cats, _) in expand(schedule, schedule["from"], schedule["to"]).items():
        for c in cats:
            got[c].add(d)
    for cat, dates in dates_by_category.items():
        want = {parse_date(x) for x in dates}
        if got[cat] != want:
            diff = sorted(got[cat] ^ want)[:5]
            raise AssertionError(f"規則の推定が元の日付と一致しません: {cat} {diff}")
