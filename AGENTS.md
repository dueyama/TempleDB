# TempleDBを保守するAIへ

最初に[START_HERE](START_HERE.md)と[保守ガイド](docs/maintenance.md)を読み、
作業ブランチ・差分・対象DB・実行中processを確認する。同じ作業で文書全体を繰り返し読まない。

## データと運用

- 架空デモと利用者の製品DBを区別する。既存DBをデモで上書き・初期化しない。
- 旧DB/CSVの原本はread-onlyとして扱う。業務変更は理由・前後・操作者を履歴へ残す。
- 実DB、backup、認証情報、実スキャン、環境設定、ログをcommitやチャットへ含めない。
- データ構造変更はbackup・別DBでのupgrade/復元確認を行ってから明示的に適用する。
- OS全体・サービス・ネットワークを変更するときは、対象端末・実行物・実行時点・影響を説明する。
- 既存物の削除、外部公開、外部へのメッセージ送信、本番反映を変更依頼から推測しない。
- commitは利用者の指示の範囲で行い、変更理由・対象・検証を`CHANGELOG.md`または業務と分離した開発記録へ残す。

## コードの境界

- 通常業務は`app/apps/office/`、共通基盤は`app/apps/core/`、source解釈はadapterへ置く。
- `app/apps/imports/services.py`と`views.py`は互換の入口。新しい本体処理を増やさない。
- service層へHttpRequest/HttpResponse/messages/render/redirectを持ち込まない。
- 既存URL・ボタン・ラベル・帳票を、明示指示なく削除・改名・非表示にしない。
- 保存済み識別子やmigrationを、表示文言と思って一括置換しない。

## 検証

- このフォルダの`.venv`を使う。実DBの接続先を流用して試験しない。
- `.venv/bin/python bin/test_maintenance.py`で、架空データの使い捨て試験を行う。
- Windows nativeは専用手順の`.venv-windows-demo\Scripts\python.exe`を使う。
- Setup後のHTTP確認は`bin/check_demo_http.py --scratch-root ABSOLUTE_EXISTING_DIRECTORY`を使う。
  Windowsでは`--windows-native`も指定する。既存serverへ直接ログインする代わりに、架空DBの一時copyで検査する。
- 画面・印刷を変更したら該当する導線も確認し、未確認の機器・OSを検証済みと説明しない。
- 小さい変更ごとに結果を確認し、利用者の独自変更を保全する。
