"""取得 → 変換 → チェック → 配信ファイルを作る。GitHub Actions から週 1 回動かす。

使い方:  python build.py --out ../site [--previous https://<user>.github.io/<repo>] [--today 2026-11-03]
終了コード: 0 正常 / 2 一部の失敗・エラーあり（配信はする）/ 3 地域が 2 割以上減った（配信しない）/ 1 異常終了
出力:    <out>/v1/index.json, v1/regions/<code>.json, v1/categories.json, report.md, index.html
--previous を付けると、取得や変換に失敗した元・チェックで落ちた地域は、公開中の前回のファイルをそのまま使う
（失敗しても配信中のデータが消えないように）。
"""
import argparse
import hashlib
import html
import importlib
import json
import sys
import traceback
from datetime import date, datetime, timezone
from pathlib import Path

import requests

from gomi.util import dumps, http_get
from gomi.validate import Report, validate_region

HERE = Path(__file__).resolve().parent


def load_previous(base):
    """公開中の index と地域ファイル（失敗したときの予備）。"""
    if not base:
        return {}, None
    try:
        index = http_get(f"{base.rstrip('/')}/v1/index.json").json()
    except (requests.RequestException, ValueError):
        return {}, None
    return {r["id"]: r for r in index.get("regions", [])}, base.rstrip("/")


def fetch_previous_region(base, entry):
    return http_get(f"{base}/v1/{entry['url']}").content


def run(out, today, previous_base=None, sources=None):
    vocab = json.loads((HERE / "categories.json").read_text(encoding="utf-8"))
    if sources is None:
        sources = json.loads((HERE / "sources.json").read_text(encoding="utf-8"))["sources"]
    prev_index, prev_base = load_previous(previous_base)
    report, log = Report(), []
    chosen = {}  # id → (source_id, region)
    failed_sources = []
    for src in sources:
        if not src.get("enabled", True):
            continue
        try:
            module = importlib.import_module(f"gomi.sources.{src['module']}")
            regions = module.convert(src, today)
        except Exception as e:  # 1 つの元の失敗で全体を止めない
            failed_sources.append(src["id"])
            log.append(f"- ❌ {src['id']}：取得・変換に失敗 `{type(e).__name__}: {e}`")
            traceback.print_exc()
            continue
        added = 0
        for r in regions:
            if r["id"] in chosen:
                log.append(f"- {src['id']}：{r['name']}（{r['id']}）は {chosen[r['id']][0]} を優先して使わない")
                continue
            chosen[r["id"]] = (src["id"], r)
            added += 1
        log.append(f"- ✅ {src['id']}：{len(regions)} 地域（採用 {added}）")

    for sid, r in chosen.values():
        validate_region(r, report, today, vocab["categories"])

    regions_dir = out / "v1" / "regions"
    regions_dir.mkdir(parents=True, exist_ok=True)
    entries = []
    for rid, (sid, r) in sorted(chosen.items()):
        if report.errors(rid):
            log.append(f"- ⚠ {r['name']}（{rid}）はチェックでエラーがあるため新しいデータを配信しない")
            continue
        data = dumps(r).encode("utf-8")
        entries.append(_entry(r, sid, data))
        (regions_dir / f"{rid}.json").write_bytes(data)

    # 失敗した元・エラーの地域は、前回の公開ファイルを使い続ける
    have = {e["id"] for e in entries}
    for rid, e in prev_index.items():
        if rid in have:
            continue
        if e.get("source") in failed_sources or report.errors(rid):
            try:
                (regions_dir / f"{rid}.json").write_bytes(fetch_previous_region(prev_base, e))
                entries.append(e)
                log.append(f"- ↩ {e['name']}（{rid}）は前回のデータを使い続ける")
            except requests.RequestException:
                log.append(f"- ❌ {e['name']}（{rid}）の前回のデータを取れない")

    entries.sort(key=lambda e: e["id"])
    index = {"schema": "gomi-index/1",
             "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
             "regions": entries}
    (out / "v1" / "index.json").write_text(dumps(index), encoding="utf-8")
    (out / "v1" / "categories.json").write_text(dumps(vocab), encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    write_report(out, today, log, report, entries, chosen)
    write_html(out, entries, chosen)
    return report, failed_sources


def _entry(region, source_id, data):
    ends = [s.get("to") for a in region["areas"] for s in a["schedules"]]
    return {"id": region["id"], "pref": region["pref"], "name": region["name"],
            "url": f"regions/{region['id']}.json",
            "hash": "sha256:" + hashlib.sha256(data).hexdigest(), "size": len(data),
            "data_updated": region["data_updated"],
            "valid_to": None if None in ends else max(ends),
            "source": source_id}


def write_report(out, today, log, report, entries, chosen):
    lines = [f"# データ取り込みの結果（{today}）", "", f"配信する地域：{len(entries)}", "", "## 取り込み元", *log, ""]
    for level, title in (("error", "エラー（その地域は配信しない）"), ("warning", "注意")):
        items = [i for i in report.items if i[0] == level]
        lines += [f"## {title}：{len(items)} 件", ""]
        for _, rid, msg in items:
            name = chosen[rid][1]["name"] if rid in chosen else rid
            lines.append(f"- {name}（{rid}）：{msg}")
        lines.append("")
    (out / "report.md").write_text("\n".join(lines), encoding="utf-8")


def write_html(out, entries, chosen):
    """Pages のトップ。配信している地域と出典の一覧（アプリの「データの出典」画面と同じ内容）。"""
    rows = []
    for e in entries:
        r = chosen.get(e["id"], (None, None))[1]
        srcs = r["sources"] if r else []
        src = "<br>".join(f'<a href="{html.escape(s["url"])}">{html.escape(s["name"])}</a>（{html.escape(s["license"])}）'
                          for s in srcs) or html.escape(e.get("source", ""))
        rows.append(f"<tr><td>{html.escape(e['pref'])}</td><td>{html.escape(e['name'])}</td>"
                    f"<td>{html.escape(e['data_updated'])}</td><td>{src}</td></tr>")
    page = f"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>ごみ収集日データ</title>
<style>body{{font-family:sans-serif;margin:16px;max-width:960px}}table{{border-collapse:collapse;width:100%}}
td,th{{border-bottom:1px solid #ddd;padding:6px;text-align:left;font-size:14px}}</style></head><body>
<h1>ごみ収集日データ（アプリ用）</h1>
<p>自治体などが公開しているオープンデータを、アプリで使う形に変換して配信しています。
このデータとアプリは自治体の公式のものではありません（非公式）。正しい収集日は各自治体の案内で確認してください。</p>
<p>形式：<code>v1/index.json</code>（一覧）、<code>v1/regions/&lt;市区町村コード&gt;.json</code></p>
<table><tr><th>都道府県</th><th>市区町村</th><th>元データの更新日</th><th>出典（ライセンス）</th></tr>
{''.join(rows)}</table></body></html>"""
    (out / "index.html").write_text(page, encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HERE.parent / "site"))
    ap.add_argument("--previous", default="")
    ap.add_argument("--today", default="")
    args = ap.parse_args()
    today = date.fromisoformat(args.today) if args.today else date.today()
    prev_count = len(load_previous(args.previous)[0])
    report, failed = run(Path(args.out), today, args.previous)
    count = len(json.loads((Path(args.out) / "v1" / "index.json").read_text(encoding="utf-8"))["regions"])
    print((Path(args.out) / "report.md").read_text(encoding="utf-8")[:3000])
    if prev_count and count < 0.8 * prev_count:
        print(f"地域の数が前回 {prev_count} → {count} に減ったため、配信しない")
        sys.exit(3)
    # エラーや失敗があっても配信は続ける（その地域だけ前回のまま）。終了コード 2 で Actions に知らせる
    # （終了コード 1 は Python の異常終了。そのときは配信しない）
    sys.exit(2 if report.errors() or failed else 0)


if __name__ == "__main__":
    main()
