# gomi-data

ごみ収集日アプリ（ERU CLARISSA）が使う、収集日データの取り込みと配信。
自治体などが公開しているオープンデータを取得し、共通形式の JSON に変換・チェックして GitHub Pages で配信する（毎週月曜 3:00）。

- 配信：https://eru-clarissa.github.io/gomi-data/ （一覧と出典）、`v1/index.json`、`v1/regions/<市区町村コード>.json`
- 形式：[pipeline/SCHEMA.md](pipeline/SCHEMA.md)　使い方：[pipeline/README.md](pipeline/README.md)

## データの出典とライセンス
配信データは、各地域ファイルの `sources` に書いた元データ（CC BY 4.0 など）を加工したもの。利用するときは元データの出典を表示すること。
このデータは自治体の公式のものではない（非公式）。正しい収集日は各自治体の案内で確認すること。
