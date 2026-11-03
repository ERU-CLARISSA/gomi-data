# 収集日データの取り込み（タスク2）

自治体などが公開しているオープンデータを取得し、共通形式（[SCHEMA.md](SCHEMA.md)）の JSON に変換・チェックして、GitHub Pages で配信する。
**競合アプリ・民間サービスのデータは使わない。** ライセンスが明記されたオープンデータだけを使い、出典を各地域のファイルと Pages のトップに出す。

## 構成
| ファイル | 役割 |
|---|---|
| `sources.json` | 取り込み元の一覧（上ほど優先。自治体の一次データを先に置く） |
| `gomi/model.py` | 規則＋例外日の展開（アプリの Dart 側も同じ規則で作る） |
| `gomi/infer.py` | 日付入りカレンダーから規則（毎週・第n・隔週・季節限定）と例外日を推定 |
| `gomi/sources/japan_gomi_data.py` | tecolicom/japan-gomi-data（CC BY 4.0、YAML）。全日で元データの意味と一致するか自己照合する |
| `gomi/sources/nagano_city.py` | 長野市 ごみ収集カレンダー（CC BY 4.0、日付入り CSV の zip） |
| `gomi/sources/bunkyo_city.py` | 文京区 ごみと資源の収集日（CC BY、曜日の CSV） |
| `gomi/sources/cities.py` | 自治体のオープンデータ（2026-11 追加：金沢市・津幡町・佐賀市・小郡市・生駒市・大分市・三郷町）。共通部分は `tables.py` |
| `gomi/jpexpr.py` | 表に書いてある収集日の書き方（「火1 火3」「第1・3火」「水2:4-3」「金3（1 金4）」など）→ 規則 |
| `gomi/validate.py` | チェック（形・日付の矛盾・欠け）。エラーの地域は配信しない |
| `gomi/ics.py` | .ics への変換（RRULE／EXDATE／RDATE） |
| `build.py` | 取得 → 変換 → チェック → `site/`（index.json・地域ファイル・report.md・index.html） |
| `../.github/workflows/data.yml` | 週 1 回（月曜 3:00）実行して Pages に配信 |

## 手元で動かす
```
cd C:\D\dev2\gomi_data\pipeline
..\.venv\Scripts\python -m pip install -r requirements.txt
..\.venv\Scripts\python -X utf8 -m unittest discover -s tests -t .
..\.venv\Scripts\python -X utf8 build.py --out ..\site
```
結果は `..\site\report.md`。

## 取り込み元を足すとき
1. `gomi/sources/<名前>.py` に `convert(cfg, today)` を書く（地域データのリストを返す）。日付入りなら `infer_schedule` を使う。
2. `sources.json` に足す。ライセンスと出典 URL を `sources` に必ず入れる。
3. テストとビルドを通し、report.md のエラー・注意を見る。

## 失敗したとき
- 取り込み元が取れない・変換に失敗した → その元の地域は、公開中の前回のファイルを使い続ける（終了コード 2、Actions は notify が赤）。
- 地域の数が前回より 2 割以上減った → 配信しない（終了コード 3）。
- 地域ファイルにはビルド日時を入れないので、中身が同じならハッシュも同じ。アプリは index.json のハッシュが変わった地域だけ取り直す。
