"""自治体のオープンデータ（CSV・Excel）の変換。sources.json の "city" で選ぶ。

2026-11-03 に洗い出した「今年度のデータがあり、すぐ変換できる」自治体（gomi_app の tools/data_survey/out/summary.md）。
大津市（土曜収集をやめた 2024-10 より前の内容）と大田区（曜日の表が令和7年版）は、古いので入れていない。
年度が替わったら FY と URL を確かめる（新しい年度のファイルが出ていないかは、毎年 3〜4 月に見る）。
"""
import re
from collections import defaultdict
from datetime import date

from .. import jpexpr
from ..infer import infer_schedule
from ..model import parse_date, rule_matches
from . import tables as T

BODIK = "https://data.bodik.jp/dataset"
ISHIKAWA = "https://ckan.opendata.pref.ishikawa.lg.jp/dataset"
# 金沢市のオープンデータポータル（石川県のカタログと同じファイルがある）。石川県のカタログは GitHub Actions から 403 になる
KANAZAWA_PORTAL = "https://catalog-data.city.kanazawa.ishikawa.jp/dataset"


def _source(name, url, license_, org, files):
    return {"name": name, "url": url, "license": license_, "attribution": org,
            "modified": "加工あり（形式を変換）", "files": files}


def _weekday_entries(rows, header_row, town_cols, cat_cols, cats, fy, extra=None):
    """曜日の表 → entries。town_cols は地区名に使う列、cat_cols は種類の列。extra(row, schedule) で例外を足せる。"""
    head = rows[header_row]
    start, end = T.fiscal_period(fy)
    entries = []
    for row in rows[header_row + 1:]:
        if not any(row) or not row[town_cols[-1]].strip():
            continue
        rules = []
        for c in cat_cols:
            rules += jpexpr.parse(row[c], cats.key(head[c]), fy)
        sched = {"from": start.isoformat(), "to": end.isoformat(), "rules": rules, "exceptions": []}
        if extra:
            extra(row, sched)
        town = " ".join(T.clean(row[c]) for c in town_cols if T.clean(row[c]))
        entries.append({"towns": [town], "schedule": sched})
    return entries


# ---------- 金沢市（5374 の形＋月の範囲。人が読む用の列と突き合わせる） ----------
def kanazawa(cfg, today):
    fy, url = 2026, f"{ISHIKAWA}/ef2503b5-957a-4ea0-ad55-c20c48f93d3e/resource/f7eb38ee-8af5-47a9-a466-62ac9434cd7e/download/2026.csv"
    alt = f"{KANAZAWA_PORTAL}/88ff02df-c3b1-439d-82d5-bb9c46bfdd92/resource/0c07d8e8-ee46-480f-b8dc-3ab772a2bb99/download/schedule2026.csv"
    rows = T.read_rows([url, alt], "csv", cache_name="kanazawa_2026.csv")
    head = rows[0]
    # 「資源回収（29〜31 日は容プラのみ）」は資源（名前の「プラ」でプラスチックにしない）
    cats = T.Categories({T.clean(head[5]).replace(" ", ""): "recyclables"})

    def extra(row, sched):
        sched["exceptions"] = T.closure_exceptions(parse_date(_slash(row[7])), parse_date(_slash(row[8])), sched)
        # 人が読む用の列（「毎週月曜 毎週木曜」「第2水曜」）と、記号の列の曜日・第n が同じか
        for coded, plain in ((3, 9), (4, 10), (5, 11), (6, 12)):
            # 説明の列は、月を限った回（1 月だけ第4金、29〜31 日の第5週など）を省いて書いている。
            # 説明にある曜日はすべて記号の列にあり、記号の列にしかないものは月を限った回だけ、なら同じとみなす
            coded_rules = jpexpr.parse(row[coded], "x", fy)
            a = _days_of(coded_rules)
            b = _days_of(jpexpr.parse(row[plain], "x", fy))
            limited = _days_of([r for r in coded_rules if r.get("from") or r.get("to")])
            if not b <= a or not (a - b) <= limited:
                raise ValueError(f"金沢市 {row[0]}：{head[coded]} の記号「{row[coded]}」と説明「{row[plain]}」が違う")

    entries = _weekday_entries(rows, 0, [0], [3, 4, 5, 6], cats, fy, extra)
    return [T.region("17201", "石川県", "金沢市", "https://www.city.kanazawa.ishikawa.jp/",
                     "2026-06-15",
                     _source("金沢市 地区別ごみ収集カレンダー（石川県オープンデータカタログ）", url.rsplit("/resource", 1)[0],
                             "CC BY", "金沢市", [url]),
                     cats.info, T.group_areas(entries),
                     ["「資源回収」は、29〜31 日は容器包装プラスチックだけです（金沢市の注記）。"])]


def _slash(s):
    y, m, d = (int(x) for x in s.split("/"))
    return date(y, m, d).isoformat()


def _days_of(rules):
    """規則の曜日と第n の組（月の範囲は見ない）"""
    out = set()
    for r in rules:
        for d in r.get("byday", []):
            out |= {(d, n) for n in (r.get("nth") or [0])}
    return out


# ---------- 津幡町（「金３（1　金4）」＝1 月だけ第4金、休止期間の列） ----------
def tsubata(cfg, today):
    fy = 2026
    url = f"{ISHIKAWA}/5f7215f4-9996-4a9d-af2f-e55f9e08477f/resource/c9b84607-8b56-4df9-9eea-30cd983aca8e/download/173614_recycle_calendar.csv"
    alt = f"{KANAZAWA_PORTAL}/3730b997-b2ae-438b-80d6-22962091510c/resource/0547c745-9631-4a45-a8d5-c5a59a6921a5/download/173614_recycle_calendar.csv"
    rows = T.read_rows([url, alt], "csv", cache_name="tsubata_2026.csv")
    cats = T.Categories()

    def extra(row, sched):
        sched["exceptions"] = T.closure_exceptions(parse_date(row[9]), parse_date(row[10]), sched)

    entries = _weekday_entries(rows, 0, [3, 4], [5, 6, 7, 8], cats, fy, extra)
    return [T.region("17361", "石川県", "津幡町", "https://www.town.tsubata.lg.jp/page/1363.html", "2026-08-13",
                     _source("津幡町 ごみカレンダー（石川県オープンデータカタログ）", url.rsplit("/resource", 1)[0],
                             "CC BY", "津幡町", [url]),
                     cats.info, T.group_areas(entries), ["粗大ごみは、収集日の 1 週間前までに予約が必要です（津幡町の案内）。"])]


# ---------- 佐賀市（5374 の形。年末年始は元データにない） ----------
def saga(cfg, today):
    fy = 2026
    url = f"{BODIK}/f4e0b6e8-c70e-481d-a5f1-7df3b6ae569d/resource/3ce9911c-7ee9-409f-abea-9ee46572d668/download/r8_.csv"
    rows = T.read_rows(url, "csv", cache_name="saga_r8.csv")
    cats = T.Categories()
    entries = _weekday_entries(rows, 0, [1], [3, 4, 5, 6], cats, fy)
    for e, row in zip(entries, [r for r in rows[1:] if any(r) and r[1].strip()]):
        e["group"] = T.clean(row[7]) + ("地区" if re.fullmatch(r"[A-Z]", T.clean(row[7])) else "")
        e["schedule"]["unknown"] = T.year_end_unknown(fy)
    return [T.region("41201", "佐賀県", "佐賀市", "https://www.city.saga.lg.jp/main/412.html", "2026-10-01",
                     _source("佐賀市ごみカレンダーデータ（BODIK）", f"{BODIK}/f4e0b6e8-c70e-481d-a5f1-7df3b6ae569d",
                             "CC BY", "佐賀市", [url]),
                     cats.info, T.group_areas(entries),
                     ["地区（A〜N、大和①など）は、佐賀市のごみカレンダーの地区です。", "年末年始（12/29〜1/3）の収集は、このデータに入っていません。"])]


# ---------- 小郡市（5374 に近い形。備考に休みの日と「5月は火2」などの例外） ----------
OGORI_FIXES = {"202606219": "20260619"}  # 元データの打ち間違い（同じ行の剪定枝はすべて第3金曜なので 6/19）


def ogori(cfg, today):
    fy = 2026
    url = f"{BODIK}/bcbf22fa-64ee-401d-9a2f-5d925c47f7ed/resource/f8ca70bc-650c-4bf1-bcb2-51675bc0ff29/download/10014_gomishu2bi_2026.csv"
    rows = T.read_rows(url, "csv", cache_name="ogori_2026.csv")
    for row in rows:
        for i, v in enumerate(row):
            for bad, good in OGORI_FIXES.items():
                row[i] = v.replace(bad, good)
    head = rows[0]
    cats = T.Categories({"不燃・ビン・粗大・ペットボトル": "non_burnable"})

    def extra(row, sched):
        note = T.clean(row[8])
        burn = cats.key(head[3])
        for m in re.finditer(r"(\d{1,2})月(\d{1,2})日", (re.search(r"燃えるごみ収集が休みの日[(（](.*?)[)）]", note) or [None, ""])[1]):
            d = date(fy if int(m.group(1)) >= 4 else fy + 1, int(m.group(1)), int(m.group(2)))
            sched["exceptions"].append({"date": d.isoformat(), "cancel": [burn], "note": "燃えるごみは休み"})
        # 「（不燃・ビン・粗大・ペットボトルの5月は火2）」→ その種類はその月だけ別の日
        for m in re.finditer(r"[(（]([^()（）]+?)の(\d{1,2})月は([^()（）]+?)[)）]", note):
            label, month, alt = m.group(1), int(m.group(2)), m.group(3)
            col = next((c for c in range(3, 8) if T.clean(head[c]) == T.clean(label) or T.clean(label) in T.clean(head[c])), None)
            if col is None:
                raise ValueError(f"小郡市 {row[0]}：備考の種類「{label}」が列にない")
            key = cats.key(head[col])
            ranges = jpexpr.fy_month_ranges(fy, jpexpr.months_except(month))
            others = [r for r in sched["rules"] if r["category"] != key]
            mine = [r for r in sched["rules"] if r["category"] == key and r["freq"] != "dates"]
            dates = [r for r in sched["rules"] if r["category"] == key and r["freq"] == "dates"]
            sched["rules"] = (others + jpexpr._with_ranges(mine, ranges)
                              + jpexpr._with_ranges(jpexpr.parse(alt, key, fy), jpexpr.fy_month_ranges(fy, [(month, month)]))
                              + dates)
        sched["exceptions"].sort(key=lambda e: e["date"])
        sched["unknown"] = T.year_end_unknown(fy)

    entries = _weekday_entries(rows, 0, [0], [3, 4, 5, 6, 7], cats, fy, extra)
    return [T.region("40216", "福岡県", "小郡市", "https://www.city.ogori.fukuoka.jp/197/700/5165", "2026-03-25",
                     _source("ごみ収集日（小郡市）（共通フォーマット）（BODIK）", f"{BODIK}/bcbf22fa-64ee-401d-9a2f-5d925c47f7ed",
                             "CC BY 4.0", "小郡市", [url]),
                     cats.info, T.group_areas(entries),
                     ["ゴールデンウィーク・お盆・年末年始は収集日がずれることがあります（小郡市の案内）。",
                      "年末年始（12/29〜1/3）の収集は、このデータに入っていません。"])]


# ---------- 生駒市（曜日の表＋祝日に収集する・しないの表） ----------
def ikoma(cfg, today):
    fy = 2026
    base = f"{BODIK}/640d9544-d11a-4935-b2ad-55ade7014420/resource"
    url = f"{base}/92f6f117-09df-4b2e-88f2-e92ea68664d0/download/r8arealist.xls"
    hol_url = f"{base}/17444b3c-5fef-4d54-9203-e7e695e8d375/download/r8collectlist.xls"
    rows = T.read_rows(url, "xls", cache_name="ikoma_r8.xls")
    head = rows[0]
    cats = T.Categories({T.clean(head[4]).replace(" ", ""): "recyclables"})
    keys = [cats.key(head[c]) for c in (2, 3, 4)]
    holidays = []
    for r in T.read_rows(hol_url, "xls", cache_name="ikoma_r8_holidays.xls"):
        m = re.match(r"令和(\d+)年(\d+)月(\d+)日", T.clean(r[0]))
        if m:
            d = date(2018 + int(m.group(1)), int(m.group(2)), int(m.group(3)))
            holidays.append((d, _ikoma_cats(r[2], keys), T.clean(r[3])))

    def extra(row, sched):
        for d, stop, name in holidays:
            hit = [k for k in stop if any(x["category"] == k and rule_matches(x, d) for x in sched["rules"])]
            if hit:
                sched["exceptions"].append({"date": d.isoformat(), "cancel": hit, "note": f"{name}は休み"})
        sched["unknown"] = T.year_end_unknown(fy)

    entries = _weekday_entries(rows, 0, [0], [2, 3, 4], cats, fy, extra)
    for e, row in zip(entries, [r for r in rows[1:] if any(r) and r[0].strip()]):
        e["group"] = f"地区番号{row[1]}"
    return [T.region("29209", "奈良県", "生駒市", "https://www.city.ikoma.lg.jp/0000040206.html", "2026-03-13",
                     _source("ごみ収集日程表（BODIK）", f"{BODIK}/640d9544-d11a-4935-b2ad-55ade7014420", "CC BY 4.0", "生駒市",
                             [url, hol_url]),
                     cats.info, T.group_areas(entries),
                     ["祝日の収集は、生駒市の「祝日のごみ収集について」の表を反映しています。",
                      "年末年始（12/29〜1/3）の収集は、このデータに入っていません。"])]


def _ikoma_cats(text, keys):
    t = T.clean(text)
    if not t:
        return []
    if "全部" in t:
        return list(keys)
    out = []
    if "燃える" in t:
        out.append(keys[0])
    if "プラ" in t:
        out.append(keys[1])
    if re.search(r"小型|金属|びん|缶|ペット|われもの|有害", t):
        out.append(keys[2])
    return out


# ---------- 大分市（カレンダー番号ごとの日付の一覧。地区との対応表は公開データにない） ----------
def oita(cfg, today):
    url = f"{BODIK}/1365d0e4-d7aa-4a3c-85a5-172d1cdd910c/resource/85ca6d28-5a4f-4729-b1cd-2c920f4668e3/download/2026schedule.csv"
    rows = T.read_rows(url, "csv", cache_name="oita_2026.csv")
    cats = T.Categories()
    by_cal = defaultdict(lambda: defaultdict(list))
    for r in rows[1:]:
        if len(r) < 5 or not r[1].strip():
            continue
        y, m, d = (int(x) for x in r[4].strip().split("/"))
        by_cal[int(r[1])][cats.key(r[3])].append(date(y, m, d))
    start, end = T.fiscal_period(2026)
    areas = []
    for no in sorted(by_cal):
        sched = infer_schedule(by_cal[no], start, end)
        areas.append({"id": str(no), "name": f"カレンダー{no}", "towns": [{"name": f"カレンダー{no}"}], "schedules": [sched]})
    return [T.region("44201", "大分県", "大分市", "https://www.city.oita.oita.jp/kurashi/gomi/shushunitte/index.html",
                     "2026-09-09",
                     _source("ごみ収集カレンダー（BODIK）", f"{BODIK}/1365d0e4-d7aa-4a3c-85a5-172d1cdd910c", "CC BY 4.0", "大分市", [url]),
                     cats.info, areas,
                     ["お手元の「ごみ収集カレンダー」の番号で選んでください。住所とカレンダー番号の対応は、大分市の公式サイト（住所別検索）で確認できます。"])]


# ---------- 三郷町（日付×地区の表。1 つのマスに「可燃ごみ・ガス缶スプレー缶」のように 2 種類） ----------
def misato(cfg, today):
    url = f"{BODIK}/35c5dbff-5ffd-4796-a74f-1172c824640b/resource/fe1a7675-1750-4cb8-8c90-410be530b227/download/293431_garbage_calendar.xlsx"
    rows = T.read_rows(url, "xlsx", cache_name="misato_2026.xlsx")
    head = rows[0]
    cols = [(c, T.clean(head[c])) for c in range(2, len(head)) if T.clean(head[c])]
    cats = T.Categories()
    days = [r for r in rows[1:] if r and re.fullmatch(r"\d{4}-\d{2}-\d{2}", r[0] or "")]
    # 「可燃ごみ・ガス缶スプレー缶」は 2 種類。「古紙・古布類」は 1 種類。単独でも出てくる名前どうしのときだけ分ける
    alone = {T.clean(r[c]) for r in days for c, _ in cols if T.clean(r[c])}

    def split(cell):
        parts = [x.strip() for x in cell.split("・")]
        return parts if len(parts) > 1 and all(p in alone for p in parts) else [cell]

    by_area = {name: defaultdict(list) for _, name in cols}
    for r in days:
        d = parse_date(r[0])
        for c, name in cols:
            if T.clean(r[c]):
                for label in split(T.clean(r[c])):
                    by_area[name][cats.key(label)].append(d)
    start, end = T.fiscal_period(2026)
    entries = [{"towns": [name], "schedule": infer_schedule(by_area[name], start, end)} for _, name in cols]
    return [T.region("29343", "奈良県", "三郷町", "https://www.town.sango.nara.jp/soshiki/17/2261.html", "2026-04-21",
                     _source("ごみカレンダー（BODIK）", f"{BODIK}/35c5dbff-5ffd-4796-a74f-1172c824640b", "公共データ利用規約 1.0（PDL1.0）",
                             "三郷町", [url]),
                     cats.info, T.group_areas(entries))]


CITIES = {"kanazawa": kanazawa, "tsubata": tsubata, "saga": saga, "ogori": ogori, "ikoma": ikoma, "oita": oita, "misato": misato}


def convert(cfg, today):
    return CITIES[cfg["city"]](cfg, today)
