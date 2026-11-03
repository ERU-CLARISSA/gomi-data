"""文京区「ごみと資源の収集日」CSV（東京都オープンデータカタログ、CC BY）→ 共通形式。

元データ：1 行 = 町名×丁目。列 = 種類ごとの収集曜日（「火曜日・金曜日」「第1・第3木曜日」）。Shift_JIS。
期間・年末年始・祝日の情報はないので、終わりのない規則だけを作り、注意書きを付ける。
"""
import csv
import io
import re
import unicodedata

from ..model import WEEKDAYS
from ..util import http_get, last_modified

CSV_URL = "https://www.city.bunkyo.lg.jp/documents/6059/syusyubi.csv"
CATALOG_URL = "https://catalog.data.metro.tokyo.lg.jp/dataset/t131059d0110060001"
JP_DAYS = {"月": "MO", "火": "TU", "水": "WE", "木": "TH", "金": "FR", "土": "SA", "日": "SU"}


def category_of(header):
    """列名 → (種類キー, 表示名)。"""
    label = re.sub(r"（週\d回）|（月\d回）", "", header).strip()
    if label.startswith("可燃"):
        return "burnable", label
    if label.startswith("不燃"):
        return "non_burnable", label
    if "プラスチック" in label:
        return "plastic", label
    if label.startswith("資源"):
        return "recyclables", label
    raise ValueError(f"文京区：知らない列「{header}」")


def parse_days(text, category):
    """「火曜日・金曜日」「第1・第3木曜日」→ 規則。"""
    text = unicodedata.normalize("NFKC", text).strip()
    m = re.fullmatch(r"(第\d+(?:・第?\d+)*)([月火水木金土日])曜日", text)
    if m:
        # 「第1・第3」は月の n 回目と解釈（文京区の表記からの推定。未確認なので notes に書く）
        return {"category": category, "freq": "monthly", "byday": [JP_DAYS[m.group(2)]],
                "nth": [int(x) for x in re.findall(r"\d+", m.group(1))], "nth_mode": "occurrence"}
    days = re.findall(r"([月火水木金土日])曜日", text)
    if not days or re.sub(r"[月火水木金土日]曜日|・", "", text):
        raise ValueError(f"文京区：読めない曜日「{text}」")
    return {"category": category, "freq": "weekly",
            "byday": sorted((JP_DAYS[d] for d in days), key=WEEKDAYS.index)}


def convert(cfg, today):
    res = http_get(cfg.get("csv_url", CSV_URL))
    updated = last_modified(res, today.isoformat())
    rows = list(csv.reader(io.StringIO(res.content.decode("cp932"))))
    header, rows = rows[0], [r for r in rows[1:] if r and r[0].strip()]
    cols = [(i, *category_of(h)) for i, h in enumerate(header) if "曜" not in h and ("ごみ" in h or "資源" in h)]
    labels, areas = {}, {}
    for r in rows:
        rules = []
        for i, key, label in cols:
            labels[key] = label
            rules.append(parse_days(r[i], key))
        sig = repr(rules)
        area = areas.setdefault(sig, {"towns": [], "rules": rules})
        area["towns"].append({"name": f"{r[0].strip()}{r[1].strip()}"})
    out_areas = []
    for n, a in enumerate(areas.values(), 1):
        names = [t["name"] for t in a["towns"]]
        out_areas.append({
            "id": str(n),
            "name": names[0] + (f" ほか{len(names) - 1}地区" if len(names) > 1 else ""),
            "towns": a["towns"],
            "schedules": [{"from": updated, "to": None, "rules": a["rules"], "exceptions": []}],
        })
    return [{
        "schema": "gomi-schedule/1",
        "id": "13105", "pref": "東京都", "name": "文京区",
        "data_updated": updated,
        "sources": [{"name": "文京区 ごみと資源の収集日（東京都オープンデータカタログ）", "url": CATALOG_URL,
                     "license": "CC BY 4.0", "attribution": "文京区",
                     "modified": "加工あり（曜日の表を規則に変換）", "files": [res.url]}],
        "categories": {k: {"label": v} for k, v in labels.items()},
        "notes": ["年末年始・祝日の収集の変更は、このデータに入っていません。区のお知らせを確認してください。",
                  "「第1・第3〇曜日」は、その月の1回目・3回目の〇曜日として計算しています。"],
        "areas": out_areas,
    }]
