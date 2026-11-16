# 配布先での保守テスト

アプリを変更した後に、スターターのルートで実行します（macOS / Linux / WSL2）:

```bash
.venv/bin/python -I -B bin/test_maintenance.py
```

`setup.sh`で導入する通常のアプリ依存とDjangoのテスト機能だけを使います。
pytestの追加導入、製品DBの停止、Web serverの起動は不要です。
作業に必要な依存を変更した場合は、先にその変更を確認して環境を準備してください。
テストコマンド自体はpackageのinstallやネット接続を行いません。

大きい一時成果物の保存先が指定されている環境では、既存の一時領域を明示します。
指定先が利用できなければ停止し、別の場所へ自動fallbackしません。

```bash
.venv/bin/python -I -B bin/test_maintenance.py --scratch-root /path/to/external/scratch
```

## 対象と隔離

- 対象は現在の`app/apps`、`app/config`、`app/static`、`app/templates`のソースです。
- テストは`maintenance/test_*.py`、データは`datasets/synthetic_demo_v1`の架空データです。
- これらだけを毎回新しい一時領域へコピーし、一時SQLiteをmigrationから作ります。
- `.env`、`current`、`runtime`、`data/private`、既存のデモDB・製品DBはコピーしません。
- 子processの環境変数を作り直し、呼出元のDB接続先・tenant・API key・Python pathを引き継ぎません。
- `apps` / `config` / `maintenance`は一時copyからだけimportします。venvのeditable installが
  元のアプリを指していても、欠けたmoduleを元環境から補わず失敗させます。
- 自動backup / Calendar同期middlewareを外し、Python socketによる接続を拒否します。
- 成功・失敗・タイムアウト時は作成した一時領域を片付けます。cleanupできない場合は失敗です。
- テスト0件や全件skipを成功扱いにしません。失敗時は終了コードが非0になります。

これは通常の設定混入・誤接続を防ぐテスト実行環境で、任意の悪意あるPythonコードを封じる
OS sandboxではありません。ソースとテストをレビューしてから実行してください。
また、既存DB内の寺院設定やデータ品質そのものの検証には使いません。

## 最小の保証範囲

- 新規DBへの全migration適用、demo identityと隔離先
- 架空の戸主・人物・法要データの基本関係
- ログイン・ログアウト・未認証アクセスの制限
- 主要画面のHTTP応答とHTML生成
- 法要の予定・勤修済み保存、リンク法要の勤修情報共有と履歴
- 製品モードで架空データ投入を拒否するguard

帳票の見た目、全業務、全権限パターン、PostgreSQL固有の挙動、実機のbackup / restoreや
Windows nativeの受入は、この最小テストの成功だけでは保証しません。

## AIと増やすとき

変更対象に対応する`test_*.py`をこのdirectoryへ追加します。Django `TestCase`と架空fixtureを使い、
実DB・private file・外部API・開発元の`tests/`へ依存しないようにします。
テストが落ちたら不具合か意図した仕様変更かを先に調べ、通すためだけにassertを削除しません。
成功後も、変更に応じた画面確認・隔離DB rehearsal・本番適用承認は別に行います。
