# 共通形式 gomi-schedule/1

アプリが読む収集日データの形。1 市区町村 = 1 ファイル（`v1/regions/<市区町村コード>.json`）。
考え方は iCalendar の RRULE／EXDATE と同じ「規則＋例外日」で、.ics に変換できる（`gomi/ics.py`）。

## 配信するファイル
```
v1/index.json                 … 全地域の一覧（差分取得用）
v1/regions/<code>.json         … 1 市区町村のデータ
v1/categories.json             … ごみの種類の語彙（色・アイコン）
```

### index.json
```json
{
  "schema": "gomi-index/1",
  "generated_at": "2026-11-03T03:00:00Z",
  "regions": [
    {"id": "20201", "pref": "長野県", "name": "長野市", "url": "regions/20201.json",
     "hash": "sha256:…", "size": 12345, "data_updated": "2026-03-23", "valid_to": "2027-03-31",
     "source": "nagano-city"}
  ]
}
```
- アプリは `hash` が手元と違う地域だけ取り直す。`hash` は地域ファイルのバイト列の SHA-256。
- 地域ファイルにはビルド日時を入れない（中身が変わらなければ `hash` も変わらない）。

### regions/<code>.json
```json
{
  "schema": "gomi-schedule/1",
  "id": "20201",                       // 全国地方公共団体コード（5 桁、検査数字なし）
  "pref": "長野県", "name": "長野市",
  "data_updated": "2026-03-23",        // 元データの更新日（アプリの「最終更新日」）
  "sources": [ {"name": "長野市 ごみ収集カレンダー（オープンデータ）", "url": "…",
                "license": "CC BY 4.0", "attribution": "長野市", "modified": "加工あり（形式を変換）"} ],
  "categories": { "burnable": {"label": "可燃ごみ"} },   // この地域での呼び方
  "notes": ["…"],                      // 利用者向けの注意（年末年始が未反映、など）
  "areas": [
    {"id": "1", "name": "カレンダー1（第一）",
     "towns": [{"name": "第一", "yomi": "だいいち"}],   // 地区の選択肢。yomi は任意
     "schedules": [ {"from": "2026-04-01", "to": "2027-03-31",
                      "rules": [ … ], "exceptions": [ … ], "unknown": [ … ]} ]}
  ]
}
```
- `areas` は収集日程が同じ地区のまとまり（コース）。利用者は `towns` の名前から選ぶ。
- `schedules` は期間ごと（版の切り替わり）。期間は重ならない。`to` が null なら終わりなし（曜日だけの元データ）。
- 期間の外、`unknown` の中の日は「分からない」。収集なしと断定しない。

## 規則（rules）
1 件 = 1 種類の 1 つの規則。同じ種類に複数の規則があってもよい。
| freq | 項目 | 意味 | RRULE |
|---|---|---|---|
| `weekly` | `byday` | 毎週（例 `["MO","TH"]`） | `FREQ=WEEKLY;BYDAY=MO,TH` |
| `weekly` | `byday`,`interval`,`anchor` | 隔週など。`anchor` は収集がある日（起点日）。`anchor` の週から `interval` 週ごと | `FREQ=WEEKLY;INTERVAL=2;BYDAY=TU`＋`DTSTART=anchor` |
| `monthly` | `byday`,`nth`,`nth_mode` | 第n曜日。`nth` は 1〜5、`-1` は最終 | `FREQ=MONTHLY;BYDAY=2WE,4WE`（`occurrence` のときだけ） |
| `dates` | `dates` | 日付の一覧（規則にできないもの） | `RDATE` |

- どの規則にも `from`／`to`（任意）を付けられる。その期間だけ有効（季節限定。例：剪定枝は 4〜12 月の毎週月曜）。.ics では DTSTART／UNTIL になる。
- **`nth_mode`（必須）**：`occurrence`＝その月の n 回目の曜日（「第2水曜」＝2回目の水曜）。`week`＝日曜始まりのカレンダーで n 段目の週にある曜日（1 日が土曜なら、翌日の日曜は第2週）。`week` は RRULE で書けないので .ics では日付に展開する。
- 祝日は、元データが「祝日は休み」としているときだけ例外日にする。何も書かなければ祝日も収集する。

## 例外日（exceptions）
```json
{"date": "2027-01-01", "cancel": ["*"], "note": "年末年始"}
{"date": "2026-12-30", "add": ["burnable"], "note": "臨時収集"}
{"date": "2026-05-04", "cancel": ["burnable"], "add": ["plastic"]}
```
- その日の種類 ＝（規則の種類 − `cancel`）＋ `add`。`"*"` はすべて休み。
- 例外日に当たる日は、アプリの通知で「いつもと違います」と出す。

## 利用者の入力（アプリ内だけ）
利用者のカスタム地域・上乗せの予定も同じ形（areas の 1 件）で端末に保存する。配信データは上書きしない。

## ごみの種類（categories.json）
キーは全国共通（`burnable` など）。表示名は地域ファイルの `categories` を優先し、色とアイコンは語彙から取る（色だけで区別しないようにアイコンを必ず持つ）。知らないキーは `other` として表示する。
