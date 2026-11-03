"""長野市「ごみ収集カレンダー（オープンデータ）」→ 共通形式。

元データ：年度ごとの zip。中に 42 個のカレンダー（gomi_calendar_<年度>_<番号>.csv）と、
番号と地区の対応表（gomi_calendar_chiku.csv）が入っている。
カレンダーは 1 行 = 1 種類、列 = 日付、収集日に「○」。UTF-8（BOM 付き）。ライセンスは CC BY 4.0。
"""
import csv
import io
import re
import zipfile
from datetime import date, datetime

from ..infer import infer_schedule
from ..util import http_get

PAGE_URL = "https://www.city.nagano.nagano.jp/n023500/contents/p006280.html"
BASE = "https://www.city.nagano.nagano.jp"

# 元データの種類名 → 共通の種類キー
CATEGORY_MAP = {
    "可燃ごみ": "burnable",
    "不燃ごみ": "non_burnable",
    "資源プラスチック": "plastic",
    "プラスチック製容器包装": "plastic",  # 令和7年度まで
    "紙": "paper",
    "缶、スプレー缶、カセットボンベ缶": "beverage_can",
    "ペットボトル": "pet_bottle",
    "ビン": "glass_bottle",
    "乾電池": "battery",
    "剪定枝葉等": "yard_waste",
}


def list_editions(page_html):
    """ページから年度ごとの zip と最終更新日を読む → [(年度, url, 更新日)]（新しい順）。"""
    out = []
    for m in re.finditer(r'href="([^"]*gomi_calendar_(\d{4})\.zip)"[^<]*</a>（最終更新日：(\d{4})年(\d{1,2})月(\d{1,2})日）', page_html):
        url, fy = m.group(1), int(m.group(2))
        updated = date(int(m.group(3)), int(m.group(4)), int(m.group(5))).isoformat()
        out.append((fy, url if url.startswith("http") else BASE + url, updated))
    return sorted(out, reverse=True)


def _rows(zf, name):
    return list(csv.reader(io.StringIO(zf.read(name).decode("utf-8-sig"))))


def parse_zip(data):
    """zip → (地区の対応 {番号: [地区名]}, {番号: {種類キー: [日付]}}, 種類の表示名, 期間)。"""
    zf = zipfile.ZipFile(io.BytesIO(data))
    chiku = {}
    for r in _rows(zf, next(n for n in zf.namelist() if n.endswith("chiku.csv")))[1:]:
        if r and r[0].strip().isdigit():
            chiku[r[0].strip()] = [x.strip() for x in r[2:] if x.strip()]
    calendars, labels, period = {}, {}, None
    for name in zf.namelist():
        m = re.search(r"gomi_calendar_\d{4}_(\d+)\.csv$", name)
        if not m:
            continue
        rows = _rows(zf, name)
        header = rows[0]
        first = next(i for i, v in enumerate(header) if re.fullmatch(r"\d{4}/\d{1,2}/\d{1,2}", v))
        days = [datetime.strptime(v, "%Y/%m/%d").date() for v in header[first:]]
        period = (days[0], days[-1])
        cats = {}
        for r in rows[1:]:
            if len(r) <= first or not r[1].strip():
                continue
            label = r[1].strip()
            key = CATEGORY_MAP.get(label)
            if key is None:
                raise ValueError(f"長野市：知らない種類「{label}」。CATEGORY_MAP に足してください")
            labels[key] = label
            cats[key] = [d for d, v in zip(days, r[first:]) if v.strip() == "○"]
        calendars[m.group(1)] = cats
    return chiku, calendars, labels, period


def convert(cfg, today):
    """設定（sources.json の 1 件）→ 地域データのリスト。"""
    page = http_get(cfg.get("page_url", PAGE_URL)).content.decode("utf-8")
    editions = list_editions(page)[:2]  # 今年度と、3 月に出る次年度
    if not editions:
        raise RuntimeError("長野市：zip のリンクが見つかりません（ページの形が変わった可能性）")
    areas, labels, updated, used = {}, {}, None, []
    for fy, url, upd in sorted(editions):
        chiku, calendars, lab, (start, end) = parse_zip(http_get(url).content)
        if end < today:
            continue  # 終わった年度は配信しない
        labels.update(lab)
        updated = max(updated or upd, upd)
        used.append(url)
        for no, cats in calendars.items():
            towns = chiku.get(no, [])
            area = areas.setdefault(no, {"id": no, "name": f"カレンダー{no}（{'・'.join(towns)}）",
                                         "towns": [{"name": t} for t in towns], "schedules": []})
            area["schedules"].append(infer_schedule(cats, start, end))
    return [{
        "schema": "gomi-schedule/1",
        "id": "20201", "pref": "長野県", "name": "長野市",
        "data_updated": updated,
        "sources": [{"name": "長野市 ごみ収集カレンダー（オープンデータ）", "url": PAGE_URL,
                     "license": "CC BY 4.0", "attribution": "長野市",
                     "modified": "加工あり（日付の一覧を規則と例外日に変換）", "files": used}],
        "categories": {k: {"label": v} for k, v in labels.items()},
        "notes": ["地区によっては、公開データの番号と違う番号のカレンダーを使っている場合があります（長野市の注記）。"
                  "お手元の紙のカレンダーの番号を確認してください。"],
        "areas": sorted(areas.values(), key=lambda a: int(a["id"])),
    }]
