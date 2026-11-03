"""自治体の表に書いてある収集日の書き方 → 規則（共通形式の rules）。

読める書き方（全角・半角、空白・改行・「、」区切りはどれでもよい）：
- 毎週：「月 木」「月木」「火・金」「月曜\\n木曜」「火曜日・金曜日」「毎週月曜 毎週木曜」
- 第n：「火1 火3」「水2」「第2 月」「第1・第3 月」「第1・3火」「第2第4金曜」「第1・第3月曜日」（その月の n 回目の曜日）
- 月の範囲つき（5374 の形）：「水2:4-3」「火5:4-11/2-3」（4〜11 月と 2〜3 月だけ）
- ある月だけ違う：「第1・3金※１月は第３・第５」「金３（1　金4）」（1 月だけ第4金）
- 日付の一覧：「20260413 20260518」「2026/4/13」
読めない書き方は ValueError（その自治体の変換を止めて、レポートに出す）。
"""
import re
import unicodedata
from datetime import date

from .model import WEEKDAYS
from .util import month_end

JP = {"月": "MO", "火": "TU", "水": "WE", "木": "TH", "金": "FR", "土": "SA", "日": "SU"}
D = "[月火水木金土日]"


def normalize(text):
    t = unicodedata.normalize("NFKC", str(text or "")).strip()
    t = t.replace("曜日", "").replace("曜", "").replace("･", "・")
    t = re.sub(rf"(第[\d・第]+)\s+({D})", r"\1\2", t)  # 「第2 月」→「第2月」
    return t


def fy_month_ranges(fy, ranges):
    """年度 fy の「月の範囲」[(4, 11), (2, 3)] → [(from, to)]。4〜3 月（1 年）全部なら [(None, None)]。"""
    if ranges == [(4, 3)]:
        return [(None, None)]
    year = lambda m: fy if m >= 4 else fy + 1  # noqa: E731
    return [(date(year(a), a, 1), month_end(year(b), b)) for a, b in ranges]


def months_except(m):
    """年度の 4〜3 月から m 月だけ除いた範囲（例：1 月 → [(4, 12), (2, 3)]）。"""
    order = [4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2, 3]
    i = order.index(m)
    out = []
    if i > 0:
        out.append((order[0], order[i - 1]))
    if i < 11:
        out.append((order[i + 1], order[11]))
    return out


def _parse_ranges(s):
    """「4-11/2-3」→ [(4, 11), (2, 3)]。「1」（1 か月だけ）→ [(1, 1)]"""
    out = []
    for part in s.split("/"):
        a, _, b = part.partition("-")
        out.append((int(a), int(b or a)))
    return out


def _tokens(t):
    # 「/」は月の範囲（4-11/2-3）に使うので区切りにしない
    return [x for x in re.split(r"[\s、,;]+", t) if x]


def parse(text, category, fy=None):
    """書き方 1 つ → 規則のリスト。fy（年度の始まりの年）は、月の範囲や「n 月だけ違う」に必要。"""
    t = normalize(text)
    if t in ("", "-", "ー", "―", "なし", "無し", "×"):
        return []
    # ある月だけ違う：「…※1月は第3・第5」「金3（1 金4）」
    m = re.fullmatch(r"(.+?)※\s*(\d{1,2})月は(.+)", t) or re.fullmatch(r"(.+?)[（(]\s*(\d{1,2})\s+(.+?)[)）]", t)
    if m:
        base, month, alt = m.group(1), int(m.group(2)), m.group(3)
        if fy is None:
            raise ValueError(f"「{text}」：年度が分からないと月ごとの違いを書けない")
        # 「第3・第5」のように曜日がないときは、元の曜日を使う
        if not re.search(D, alt):
            alt = alt + re.search(D, base).group(0)
        return (_with_ranges(_parse_plain(base, category), fy_month_ranges(fy, months_except(month)))
                + _with_ranges(_parse_plain(alt, category), fy_month_ranges(fy, [(month, month)])))
    return _parse_plain(t, category, fy)


def _with_ranges(rules, ranges):
    out = []
    for r in rules:
        for f, to in ranges:
            out.append({**r, **({"from": f.isoformat()} if f else {}), **({"to": to.isoformat()} if to else {})})
    return out


def _parse_plain(t, category, fy=None):
    # 日付は「この日も収集」（5374 の形の「金1 金3 20261229」など）。日付だけなら日付の一覧
    date_re = r"20\d{2}(?:/\d{1,2}/\d{1,2}|-\d{2}-\d{2}|\d{4})"
    dates = re.findall(date_re, t)
    t = re.sub(date_re, " ", t).strip()
    extra = [{"category": category, "freq": "dates", "dates": sorted({_iso(d) for d in dates})}] if dates else []
    if not t:
        return extra
    weekly, nth = [], {}  # nth: (nth の組, 範囲) → 曜日
    for tok in _tokens(t):
        ranges = [(4, 3)]
        if ":" in tok:
            tok, rs = tok.split(":", 1)
            ranges = _parse_ranges(rs)
        key_r = tuple(ranges)
        if m := re.fullmatch(rf"毎週({D})", tok):
            weekly.append((m.group(1), key_r))
        elif m := re.fullmatch(rf"第(\d+(?:・?第?\d+)*)({D})", tok):
            ns = tuple(int(x) for x in re.findall(r"\d+", m.group(1)))
            nth.setdefault((ns, key_r), []).append(m.group(2))
        elif m := re.fullmatch(rf"({D})(\d)", tok):
            nth.setdefault(((int(m.group(2)),), key_r), []).append(m.group(1))
        elif re.fullmatch(rf"{D}(・?{D})*", tok):
            weekly += [(d, key_r) for d in re.findall(D, tok)]
        else:
            raise ValueError(f"読めない書き方「{tok}」（元：{t}）")
    rules = []
    for key_r in dict.fromkeys(r for _, r in weekly):
        days = sorted({JP[d] for d, r in weekly if r == key_r}, key=WEEKDAYS.index)
        rules += _ranged({"category": category, "freq": "weekly", "byday": days}, key_r, fy)
    # 曜日ごとに「第1・第3」をまとめる（「火1 火3」→ 火の第1・第3）
    by_day = {}
    for (ns, key_r), days in nth.items():
        for d in days:
            by_day.setdefault((JP[d], key_r), set()).update(ns)
    groups = {}
    for (d, key_r), ns in by_day.items():
        groups.setdefault((tuple(sorted(ns)), key_r), []).append(d)
    for (ns, key_r), days in groups.items():
        rules += _ranged({"category": category, "freq": "monthly", "byday": sorted(days, key=WEEKDAYS.index),
                          "nth": list(ns), "nth_mode": "occurrence"}, key_r, fy)
    return rules + extra


def _ranged(rule, key_r, fy):
    ranges = list(key_r)
    if ranges == [(4, 3)]:
        return [rule]
    if fy is None:
        raise ValueError("月の範囲があるのに年度が分からない")
    return _with_ranges([rule], fy_month_ranges(fy, ranges))


def _iso(d):
    if "/" in d:
        y, m, dd = (int(x) for x in d.split("/"))
        return date(y, m, dd).isoformat()
    if "-" in d:
        return d
    return f"{d[:4]}-{d[4:6]}-{d[6:]}"


# 種類の名前 → 共通の種類キー（上から順に当てる。当たらなければ other）
CATEGORY_WORDS = [
    (r"剪定|枝|草", "yard_waste"),
    (r"スプレー|ガス缶|カセット", "spray_can"),
    (r"粗大", "oversized"),
    (r"(古紙|紙).*(布|衣)|(布|衣).*(古紙|紙)", "paper_cloth"),
    (r"ペット", "pet_bottle"),
    (r"プラ", "plastic"),
    (r"(缶|かん|カン).*(びん|ビン|瓶)|(びん|ビン|瓶).*(缶|かん|カン)", "recyclables"),
    (r"缶|かん|カン", "beverage_can"),
    (r"びん|ビン|瓶", "glass_bottle"),
    (r"蛍光|有害|乾電池|電池", "hazardous"),
    (r"金属|小型家電|小型電化", "metal"),
    (r"不燃|燃えない|燃やさない|燃やせない|もえない|埋立", "non_burnable"),
    (r"可燃|燃える|燃やす|燃やせる|もえる", "burnable"),
    (r"古紙|紙", "paper"),
    (r"古布|衣類|布", "cloth"),
    (r"資源", "recyclables"),
    (r"生ごみ", "kitchen"),
]


def category_key(label):
    t = normalize(label)
    for pat, key in CATEGORY_WORDS:
        if re.search(pat, t):
            return key
    return "other"
