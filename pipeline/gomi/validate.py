"""地域データのチェック。error が 1 件でもある地域は配信しない。warning は報告だけ。

- 形：必要な項目、曜日・第n・隔週の起点、日付の書き方、種類が宣言されているか
- 矛盾：期間の重なり、同じ日の例外日の重複、休みにした種類がもともとその日にない、など
- 欠け：期間がもうすぐ終わる、次の 4 週に収集が 1 回もない、いつもより長く収集が空く
"""
import re
from datetime import timedelta
from statistics import median

from .model import WEEKDAYS, ALL, expand, parse_date, regular_categories

FREQS = {"weekly", "monthly", "dates"}


class Report:
    def __init__(self):
        self.items = []  # (level, region_id, message)

    def add(self, level, rid, msg):
        self.items.append((level, rid, msg))

    def errors(self, rid=None):
        return [i for i in self.items if i[0] == "error" and (rid is None or i[1] == rid)]


def _date_ok(s):
    try:
        parse_date(s)
        return True
    except (TypeError, ValueError):
        return False


def check_rule(rule, cats, err):
    if rule.get("category") not in cats:
        err(f"規則の種類「{rule.get('category')}」が categories にない")
    freq = rule.get("freq")
    if freq not in FREQS:
        return err(f"知らない freq「{freq}」")
    for k in ("from", "to"):
        if rule.get(k) and not _date_ok(rule[k]):
            err(f"規則の {k} が日付でない: {rule[k]}")
    if freq == "dates":
        bad = [d for d in rule.get("dates", []) if not _date_ok(d)]
        if bad or not rule.get("dates"):
            err(f"dates が空か、日付でない: {bad[:3]}")
        return
    if not rule.get("byday") or any(d not in WEEKDAYS for d in rule["byday"]):
        err(f"byday が不正: {rule.get('byday')}")
    if freq == "weekly" and rule.get("interval", 1) != 1:
        if not isinstance(rule["interval"], int) or rule["interval"] < 2:
            err(f"interval が不正: {rule['interval']}")
        elif not _date_ok(rule.get("anchor")):
            err("隔週の規則に起点日（anchor）がない")
        elif WEEKDAYS[parse_date(rule["anchor"]).weekday()] not in rule["byday"]:
            err(f"起点日 {rule['anchor']} の曜日が byday にない")
    if freq == "monthly":
        if rule.get("nth_mode") not in ("occurrence", "week"):
            err("第n の数え方（nth_mode）がない")
        if not rule.get("nth") or any(n not in (1, 2, 3, 4, 5, -1) for n in rule["nth"]):
            err(f"nth が不正: {rule.get('nth')}")


def check_schedule(s, cats, err, warn, today):
    if not _date_ok(s.get("from")) or (s.get("to") is not None and not _date_ok(s.get("to"))):
        return err(f"期間が不正: {s.get('from')}〜{s.get('to')}")
    start, end = parse_date(s["from"]), parse_date(s["to"]) if s.get("to") else None
    if end and end < start:
        return err(f"期間の終わりが始まりより前: {start}〜{end}")
    if not s.get("rules"):
        err("規則が 1 つもない")
    for r in s.get("rules", []):
        check_rule(r, cats, err)
    seen = set()
    for e in s.get("exceptions", []):
        if not _date_ok(e.get("date")):
            err(f"例外日の日付が不正: {e.get('date')}")
            continue
        d = parse_date(e["date"])
        if e["date"] in seen:
            err(f"例外日が重複: {e['date']}")
        seen.add(e["date"])
        if d < start or (end and d > end):
            warn(f"例外日 {e['date']} が期間の外")
        used = [c for c in e.get("cancel", []) + e.get("add", []) if c != ALL]
        for c in used:
            if c not in cats:
                err(f"例外日 {e['date']} の種類「{c}」が categories にない")
        regular = regular_categories(s, d)
        stray = [c for c in e.get("cancel", []) if c != ALL and c not in regular]
        if stray:
            warn(f"例外日 {e['date']}：休みにした {stray} は、もともとその日に収集がない")
        dup = [c for c in e.get("add", []) if c in regular and c not in e.get("cancel", [])]
        if dup:
            warn(f"例外日 {e['date']}：追加した {dup} は、もともとその日に収集がある")
        if ALL in e.get("cancel", []) and not regular:
            warn(f"例外日 {e['date']}：全部休みにしたが、もともと収集がない日")
    for u in s.get("unknown", []):
        if not (_date_ok(u.get("from")) and _date_ok(u.get("to"))) or parse_date(u["from"]) > parse_date(u["to"]):
            err(f"不明期間が不正: {u}")


def check_gaps(s, warn, today):
    """欠けの検査（規則が正しく読めている前提）。"""
    start = max(parse_date(s["from"]), today)
    end = parse_date(s["to"]) if s.get("to") else start + timedelta(days=365)
    if end < start:
        return
    days = expand(s, start, end)
    if (s.get("to") is None or end - start >= timedelta(days=28)) and not any(d <= start + timedelta(days=27) for d in days):
        warn(f"{start} から 4 週間、収集が 1 回もない")
    by_cat = {}
    for d, (cats, _) in sorted(days.items()):
        for c in cats:
            by_cat.setdefault(c, []).append(d)
    for c, ds in by_cat.items():
        gaps = [(b - a).days for a, b in zip(ds, ds[1:])]
        if len(gaps) < 4:
            continue
        limit = 2 * median(gaps) + 7
        for (a, b), g in zip(zip(ds, ds[1:]), gaps):
            if g > limit and not _seasonal(s, c, a, b):
                warn(f"{c}：{a}〜{b} の {g} 日間、収集がない（ふだんは {median(gaps):g} 日おき）")


def _seasonal(s, cat, a, b):
    """季節限定の規則（from/to 付き）の切れ目なら、空いて当然。"""
    return any(r["category"] == cat and (r.get("from") or r.get("to")) for r in s["rules"])


def validate_region(region, report, today, vocab):
    rid = region.get("id", "?")
    err = lambda m: report.add("error", rid, m)
    warn = lambda m: report.add("warning", rid, m)
    for k in ("schema", "id", "pref", "name", "data_updated", "sources", "categories", "areas"):
        if k not in region:
            err(f"項目「{k}」がない")
    if not re.fullmatch(r"\d{5}", str(region.get("id", ""))):
        err(f"id が 5 桁の市区町村コードでない: {rid}")
    if region.get("schema") != "gomi-schedule/1":
        err(f"schema が違う: {region.get('schema')}")
    if not region.get("sources") or any(not s.get("license") or not s.get("url") for s in region["sources"]):
        err("出典（sources の url・license）がない")
    cats = region.get("categories", {})
    for c in cats:
        if c not in vocab:
            warn(f"語彙にない種類「{c}」（アプリでは「その他」として表示）")
    if not region.get("areas"):
        return err("地区（areas）が 1 つもない")
    town_owner = {}
    for a in region["areas"]:
        aerr = lambda m, a=a: err(f"[{a.get('id')}] {m}")
        awarn = lambda m, a=a: warn(f"[{a.get('id')}] {m}")
        if not a.get("towns"):
            aerr("地区名（towns）がない")
        for t in a.get("towns", []):
            if t["name"] in town_owner and town_owner[t["name"]] != a["id"]:
                awarn(f"地区名「{t['name']}」がコース {town_owner[t['name']]} にもある")
            town_owner[t["name"]] = a["id"]
        if not a.get("schedules"):
            aerr("期間（schedules）がない")
            continue
        for s in a["schedules"]:
            check_schedule(s, cats, aerr, awarn, today)
        spans = sorted((parse_date(s["from"]), parse_date(s["to"]) if s.get("to") else None) for s in a["schedules"]
                       if _date_ok(s.get("from")))
        for (f1, t1), (f2, _) in zip(spans, spans[1:]):
            if t1 is None or t1 >= f2:
                aerr(f"期間が重なっている: {f1}〜{t1} と {f2}〜")
        if not report.errors(rid):
            for s in a["schedules"]:
                check_gaps(s, awarn, today)
    ends = [parse_date(s["to"]) for a in region["areas"] for s in a.get("schedules", []) if s.get("to") and _date_ok(s["to"])]
    open_ended = any(s.get("to") is None for a in region["areas"] for s in a.get("schedules", []))
    if ends and not open_ended:
        last = max(ends)
        if last < today:
            err(f"データの期間が終わっている（{last} まで）")
        elif last < today + timedelta(days=45):
            warn(f"データの期間が {last} で終わる。次の版の取り込みが必要")
