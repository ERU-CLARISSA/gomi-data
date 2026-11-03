"""自治体の表（CSV・Excel）を読んで地域データを組み立てる共通部分。"""
import csv
import io
import re
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path

from ..jpexpr import category_key
from ..util import http_get


CACHE = Path(__file__).resolve().parents[2] / "cache"


def fetch(urls, cache_name=None):
    """urls を順に試して中身を返す。取れたら cache/ に写しを保存する。
    どこからも取れなければ cache/ の写しを使う（石川県のカタログは GitHub Actions からの取得を 403 で断るため）。
    写しは CC BY などのオープンデータの再配布で、出典は地域ファイルの sources に書いてある。"""
    urls = [urls] if isinstance(urls, str) else urls
    errors = []
    for u in urls:
        try:
            data = http_get(u).content
            if cache_name:
                CACHE.mkdir(exist_ok=True)
                if not (CACHE / cache_name).exists() or (CACHE / cache_name).read_bytes() != data:
                    (CACHE / cache_name).write_bytes(data)
            return data
        except Exception as e:  # 次の取得先・写しを試す
            errors.append(f"{u}: {type(e).__name__}")
    if cache_name and (CACHE / cache_name).exists():
        print(f"  [写しを使う] {cache_name}（{'; '.join(errors)}）")
        return (CACHE / cache_name).read_bytes()
    raise RuntimeError("取得できない: " + "; ".join(errors))


def read_rows(url, fmt=None, sheet=0, cache_name=None):
    """表を行のリスト（文字列のリスト）で返す。CSV は UTF-8 か Shift_JIS、Excel は xlsx・xls。url はリストでもよい。"""
    data = fetch(url, cache_name)
    first = url if isinstance(url, str) else url[0]
    fmt = (fmt or first.rsplit(".", 1)[-1]).lower()
    if fmt == "xlsx":
        import openpyxl
        ws = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True).worksheets[sheet]
        return [[_cell(v) for v in row] for row in ws.iter_rows(values_only=True)]
    if fmt == "xls":
        import xlrd
        sh = xlrd.open_workbook(file_contents=data).sheet_by_index(sheet)
        return [[_xls_cell(sh, r, c) for c in range(sh.ncols)] for r in range(sh.nrows)]
    for enc in ("utf-8-sig", "cp932"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    return [[c.strip() for c in row] for row in csv.reader(io.StringIO(text))]


def _cell(v):
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def _xls_cell(sh, r, c):
    v = sh.cell_value(r, c)
    return _cell(int(v) if isinstance(v, float) and v.is_integer() else v)


def clean(s):
    return unicodedata.normalize("NFKC", s or "").replace("\n", "").strip()


class Categories:
    """表の列名 → 地域の中で重ならない種類キー。表示名は元の列名、色・アイコンは base（語彙）から。"""

    def __init__(self, overrides=None):
        self.overrides = overrides or {}  # 列名 → 語彙のキー（自動で当たらないときに指定）
        self.by_label, self.info = {}, {}

    def key(self, label):
        label = re.sub(r"\s+", "", clean(label))
        if label in self.by_label:
            return self.by_label[label]
        base = self.overrides.get(label) or category_key(label)
        key, n = base, 2
        while key in self.info:
            key, n = f"{base}_{n}", n + 1
        self.by_label[label] = key
        self.info[key] = {"label": label, **({"base": base} if key != base else {})}
        return key


def fiscal_period(fy):
    return date(fy, 4, 1), date(fy + 1, 3, 31)


def year_end_unknown(fy, reason="年末年始の収集日は元データに入っていない。自治体の案内で確認する"):
    return [{"from": date(fy, 12, 29).isoformat(), "to": date(fy + 1, 1, 3).isoformat(), "reason": reason}]


def closure_exceptions(start, end, rules_schedule):
    """休止期間（全部休み）→ 例外日。もともと収集がある日だけ。"""
    from ..model import regular_categories
    out, d = [], start
    while d <= end:
        if regular_categories(rules_schedule, d):
            out.append({"date": d.isoformat(), "cancel": ["*"], "note": "年末年始の休止"})
        d += timedelta(days=1)
    return out


def group_areas(entries, name_of=None):
    """[{"towns": [...], "schedule": {...}, "group": 名前?}] → 収集日程が同じものをまとめた areas。"""
    groups = {}
    for e in entries:
        sig = repr(e["schedule"])
        g = groups.setdefault(sig, {"towns": [], "schedule": e["schedule"], "groups": []})
        g["towns"] += [t for t in e["towns"] if t not in g["towns"]]
        if e.get("group") and e["group"] not in g["groups"]:
            g["groups"].append(e["group"])
    areas = []
    for n, g in enumerate(groups.values(), 1):
        names = g["towns"]
        if name_of:
            name = name_of(g)
        elif g["groups"]:
            name = "・".join(g["groups"])
        else:
            name = names[0] + (f" ほか{len(names) - 1}地区" if len(names) > 1 else "")
        areas.append({"id": str(n), "name": name, "towns": [{"name": t} for t in names], "schedules": [g["schedule"]]})
    return areas


def region(code, pref, name, official_url, updated, source, categories, areas, notes=()):
    return {
        "schema": "gomi-schedule/1",
        "id": code, "pref": pref, "name": name, "official_url": official_url,
        "data_updated": updated,
        "sources": [source],
        "categories": categories,
        "notes": list(notes),
        "areas": areas,
    }
