## Cursor Cloud specific instructions

単一の Python スクリプトです。ローカルサーバ、リンタ、テスト、ビルドはありません。インストールと実行コマンドは `README.md` の「インストール・実行」を参照してください。

- ベースイメージには `python3` のみあります。`python` が無いときは `python3 schedule_aggregator.py` を使います。
- `/usr/bin/google-chrome` があると Playwright の Chromium よりこちらを使います。この環境にはシステム Chrome があります。
- 全店舗の取得は数分かかります（店舗あたり `networkidle` 待ちが最大 40 秒）。ログをパイプするときは `python3 -u schedule_aggregator.py` にしないと標準出力が終わりまでバッファされます。
- 実行後に `schedule.html` がリポジトリ直下へ書かれます。`webbrowser.open` は D-Bus が無いとブラウザを前面に出せず、Chrome の D-Bus エラーが続きます。HTML 自体は生成済みなので `file:///workspace/schedule.html` を開いてください。生成物はコミットしません。
- 一部店舗はサイト構造やタイムアウトで 0 件になり、ページ上部に警告が出ます。これはスクレイパの既知の挙動で、環境の起動失敗ではありません。
