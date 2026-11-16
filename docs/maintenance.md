# AIと行う保守

入口は`AGENTS.md`、操作準備は`START_HERE.md`です。変更前にGitのbranch・差分と、
`runtime/demo.sqlite3` / `runtime/product/templedb.sqlite3`のどちらを扱うかを確認します。
大きい変更を一度に行わず、検証できた小さい単位でcommitします。

## コードの置き場

通常業務は`app/apps/office/`、共通基盤は`app/apps/core/`、取り込みは`app/apps/imports/`です。
`imports`には通常業務のモデルとmigrationも残っています。名前だけで独立削除しません。
`imports/services.py`と`views.py`へ本体処理を追加せず、意味のあるmoduleを正面の置き場にします。
寺院差分は`app/config/tenant_policy/default/`、帳票はtemplate/PDFの担当moduleを確認します。
保存済み値と表示だけの名称を区別してください。

## 隔離検証

```bash
.venv/bin/python bin/test_maintenance.py
```

このコマンドはソース・架空データを一時copyし、networkを無効にした子processで、
新規SQLiteのmigration・認証・主要画面・基本法要を検証します。既存製品DBを変更しません。
通常serviceへのrequest/response・view依存の混入も検査します。互換入口は既存の例外として区別し、
この検査だけで全architectureや業務仕様を保証するものではありません。
一時領域を指定する場合は`--scratch-root ABSOLUTE_EXISTING_DIRECTORY`を使います。
実プリンター、Google API、本番PostgreSQLや別OSは、この試験の確認範囲に含めません。

## 実HTTPとCI

Setup後は、既存の一時作業ディレクトリを指定して次も実行できます。

```bash
.venv/bin/python bin/check_demo_http.py --scratch-root /absolute/path/to/scratch
```

標準の架空DBだけを読取専用で開き、SQLite backup APIで一時コピーします。
ソースも一時コピーし、外向き通信を止めたloopbackサーバーでログイン・ホーム・戸主一覧を確認します。
毎回の識別ヘッダーで自分のサーバーであることを確認し、他の稼働サーバーへログインしません。
終了時は起動した子プロセスだけを停止し、試験コピーを破棄します。元DBを編集しません。

Windows nativeは専用venvで実行します。

```powershell
& .\.venv-windows-demo\Scripts\python.exe .\bin\test_maintenance.py
& .\.venv-windows-demo\Scripts\python.exe .\bin\check_demo_http.py --windows-native --scratch-root $env:TEMP
```

GitHub Actionsはpush、PR、手動実行時にGitHub側の一時端末で動きます。
Ubuntu/macOSとWindows ARM64でSetup、隔離保守試験、HTTP検査を行い、WindowsではVerify/Cleanupも実行します。
repositoryへの権限はcontents:readだけで、Pi・本番DB・Google/OpenAIのsecretは要求しません。
成功しても、実プリンター・PDFの見た目・Windowsの対話的なCtrl+C・WSL実機の確認とは別です。

## 更新

Templateから作ったrepositoryへ、配布元の更新が自動適用されるわけではありません。
まず利用者側の独自変更をcommitし、[更新と運用](operations.md)に従って版と差分を確認します。
codeの切り戻しと業務DBの巻き戻しを同じ操作にせず、schema変更は別DBでupgradeを確認します。
実データのあるDBをデモとしてresetしないでください。
