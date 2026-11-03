"""tecolicom/japan-gomi-data（CC BY 4.0、YAML）→ 共通形式。

元データ：municipalities/<都道府県>/<handle>/ に meta.yaml・taxonomy.yaml・<期間>/course-*.yaml。
course の rules は weekly / monthly_nth（その月の n 回目）/ monthly_specific（日付の一覧）。
overrides の意味（元リポジトリの tools/_lib/schedule.mjs の categoriesOn）：
  - cancelled があればその日は全部休み
  - category 付きの override があれば、その日は「毎週の規則の種類 ＋ override の種類」（第n・日付指定の規則は捨てる）
この意味で計算した結果と、こちらの規則だけの結果の差を、例外日（cancel / add）として持つ。
"""
import io
import re
import tarfile
from collections import defaultdict
from datetime import date, timedelta

import yaml

from ..model import categories_on, in_schedule, parse_date, regular_categories
from ..util import http_get, month_end

REPO_URL = "https://github.com/tecolicom/japan-gomi-data"
TARBALL_URL = "https://codeload.github.com/tecolicom/japan-gomi-data/tar.gz/refs/heads/main"
PERIOD_RE = re.compile(r"^(\d{4})-(\d{2})--(\d{4})-(\d{2})$")
DAY_INDEX = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


def _iso(v):
    return v.isoformat() if isinstance(v, date) else str(v)


def load_tree(data):
    """tar.gz → {リポジトリ内のパス: YAML の中身}（municipalities の下だけ）。"""
    files = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
        for m in tf.getmembers():
            path = m.name.split("/", 1)[-1]
            if m.isfile() and path.startswith("municipalities/") and path.endswith(".yaml"):
                files[path] = yaml.safe_load(tf.extractfile(m).read().decode("utf-8"))
    return files


def convert_rule(r):
    cat, pat = r["category"], r["pattern"]
    if pat == "weekly":
        return {"category": cat, "freq": "weekly", "byday": list(r["days"])}
    if pat == "monthly_nth":
        return {"category": cat, "freq": "monthly", "byday": list(r["days"]),
                "nth": list(r["occurrences"]), "nth_mode": "occurrence"}
    if pat == "monthly_specific":
        return {"category": cat, "freq": "dates", "dates": sorted(_iso(d) for d in r.get("dates") or [])}
    raise ValueError(f"japan-gomi-data：知らない pattern {pat}")


def _source_result(rules, overrides, d):
    """元データの意味での、その日の種類（overrides の扱いを元の実装に合わせる）。"""
    weekly, other = [], []
    for r in rules:
        hit = False
        if r["pattern"] in ("weekly", "monthly_nth") and d.weekday() in [DAY_INDEX[x] for x in r["days"]]:
            hit = r["pattern"] == "weekly" or (d.day - 1) // 7 + 1 in r["occurrences"]
        elif r["pattern"] == "monthly_specific":
            hit = d.isoformat() in [_iso(x) for x in r.get("dates") or []]
        if hit:
            (weekly if r["pattern"] == "weekly" else other).append(r["category"])
    if any(o.get("cancelled") for o in overrides):
        return []
    result = weekly + ([] if overrides else other)
    result += [o["category"] for o in overrides if o.get("category")]
    return list(dict.fromkeys(result))


def convert_course(course):
    meta, rules = course["metadata"], course["rules"]
    m = PERIOD_RE.match(meta["period"])
    start = date(int(m.group(1)), int(m.group(2)), 1)
    end = month_end(int(m.group(3)), int(m.group(4)))
    schedule = {"from": start.isoformat(), "to": end.isoformat(),
                "rules": [x for x in map(convert_rule, rules) if x["freq"] != "dates" or x["dates"]],  # 空の日付指定は捨てる
                "exceptions": []}
    by_date = defaultdict(list)
    for o in course.get("overrides") or []:
        by_date[_iso(o["date"])].append(o)
    for key in sorted(by_date):
        d = parse_date(key)
        want = _source_result(rules, by_date[key], d)
        have = regular_categories(schedule, d)
        if want == have:
            continue
        ex = {"date": key}
        if not want:
            ex["cancel"] = ["*"]
        else:
            if [c for c in have if c not in want]:
                ex["cancel"] = [c for c in have if c not in want]
            if [c for c in want if c not in have]:
                ex["add"] = [c for c in want if c not in have]
        notes = [o["note"] for o in by_date[key] if o.get("note")]
        if notes:
            ex["note"] = " / ".join(dict.fromkeys(notes))
        schedule["exceptions"].append(ex)
    if course.get("unknown_periods"):
        schedule["unknown"] = [{"from": _iso(u["from"]), "to": _iso(u["to"]), "reason": u["reason"]}
                               for u in course["unknown_periods"]]
    verify_course(course, schedule, by_date)
    return schedule


def verify_course(course, schedule, by_date):
    """期間の全日で、元データの意味の結果と変換後の結果が一致するか（変換の自己照合）。"""
    d, end = parse_date(schedule["from"]), parse_date(schedule["to"])
    while d <= end:
        want = _source_result(course["rules"], by_date.get(d.isoformat(), []), d)
        got, _ = categories_on(schedule, d)
        if in_schedule(schedule, d) and sorted(want) != sorted(got):
            md = course["metadata"]
            raise AssertionError(f"japan-gomi-data の変換が一致しません: {md['city']} コース{md['course']} {d} {want} != {got}")
        d += timedelta(days=1)


def convert_tree(files, today):
    """municipalities の YAML 一式 → 地域データのリスト。終わった期間は落とす。"""
    by_city = defaultdict(lambda: {"courses": []})
    for path, doc in files.items():
        parts = path.split("/")
        if len(parts) == 4 and parts[3] in ("meta.yaml", "taxonomy.yaml"):
            by_city[parts[2]][parts[3]] = doc
        elif len(parts) == 5 and parts[4].startswith("course-") and PERIOD_RE.match(parts[3]):
            by_city[parts[2]]["courses"].append(doc)
    regions = []
    for handle, c in sorted(by_city.items()):
        meta, courses = c.get("meta.yaml"), c["courses"]
        if not meta or not courses or not meta.get("code"):
            continue  # 調査だけで、収録されていない自治体
        areas = {}
        for course in sorted(courses, key=lambda x: x["metadata"]["period"]):
            md = course["metadata"]
            schedule = convert_course(course)
            if parse_date(schedule["to"]) < today:
                continue
            name = md.get("course_name_ja") or f"コース{md['course']}"
            area = areas.setdefault(md["course"], {"id": str(md["course"]), "name": name, "towns": [], "schedules": []})
            area["name"] = name  # 新しい期間の名前を使う
            towns = [{k: t[k] for k in ("name", "yomi") if t.get(k)} for t in md.get("areas") or []]
            area["towns"] = towns or [{"name": name}]
            area["schedules"].append(schedule)
        if not areas:
            continue
        taxonomy = c.get("taxonomy.yaml") or {}
        overrides = taxonomy.get("overrides") or {}
        labels = {}
        for k in taxonomy.get("categories", []):
            label = (overrides.get(k) or {}).get("label")
            labels[k] = {"label": label} if label else {}  # 表示名がなければ語彙の名前を使う
        primary = [u for u in (meta.get("source") or {}).values() if isinstance(u, str) and u.startswith("http")]
        regions.append({
            "schema": "gomi-schedule/1",
            "id": str(meta["code"]), "pref": meta.get("region_ja", ""), "name": meta["name_ja"],
            "data_updated": max(_iso(x["metadata"]["source"]["extracted_at"]) for x in courses),
            "sources": [{"name": "japan-gomi-data（tecolicom）", "url": f"{REPO_URL}/tree/main/municipalities",
                         "license": "CC BY 4.0", "attribution": "tecolicom/japan-gomi-data",
                         "modified": "加工あり（形式を変換）", "primary": primary}],
            "categories": labels,
            "notes": [],
            "areas": sorted(areas.values(), key=lambda a: (len(a["id"]), a["id"])),
        })
    return regions


def convert(cfg, today):
    return convert_tree(load_tree(http_get(cfg.get("tarball_url", TARBALL_URL), timeout=180).content), today)
