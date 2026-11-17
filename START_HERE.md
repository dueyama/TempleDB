# TempleDBのはじめ方

このフォルダをCodex等で開き、`AGENTS.md`に従って作業します。
まず「架空データで試す」か「空DBから導入を準備する」かを選んでください。
OS全体への導入や既存データの変更が必要な場合は、実行前に説明を受けて判断してください。

使いたいOSやCPUが下の手順と異なる場合も、その環境をAIに伝えて導入を相談してください。
Pythonと必要なライブラリを用意できれば、依存関係や起動方法を調整して使える環境を広げられます。
まず架空データで試し、調整した手順とログインまでの確認結果を残す進め方を推奨します。

## 架空データで試す

macOS / Linux / WSL2で、Python 3.13以上を用意します。

```bash
./bin/setup.sh
./bin/run_demo.sh
```

setupはPython仮想環境、依存関係、架空データをこのフォルダ内に準備します。
`http://127.0.0.1:8011/`のデモに、初期ユーザー`demo` / パスワード`demo`でログインします。
この共通パスワードは架空デモ専用です。外部から接続できる状態で使いません。
ターミナルのControl-Cで停止します。データは`runtime/demo.sqlite3`にあります。

Windows 11 ARM64 nativeでは、Python 3.13のnative ARM64版を用意し、PowerShellから実行します。
WSLは不要です。

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\bin\windows_demo.ps1 -Action Setup
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\bin\windows_demo.ps1 -Action Verify
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\bin\windows_demo.ps1 -Action Start
```

Setupが同梱の架空データから`runtime/windows-demo/demo.sqlite3`を作成します。
既存DBは再投入せず保持します。停止は起動したPowerShellで`Ctrl+C`です。
Windows nativeの入口は合成デモ専用です。詳細・撤去は[専用手順](docs/windows_native_demo.md)へ。
確認済みの環境と、ほかの環境へ広げる進め方は[環境と受入範囲](docs/platforms.md)を参照してください。

## 空のDBで導入を準備する

共通setupの後、次を実行します。

```bash
./bin/init_product_db.sh
./bin/create_product_admin.sh
./bin/run_product.sh
```

製品DBは`runtime/product/templedb.sqlite3`で、架空デモとは別です。
source設定には「未登録（導入準備）」という論理的な仮設定があります。MDBファイルは同梱しません。
旧データの取り込みを行う際に、実際のsourceを登録します。
管理者パスワードは対話で設定し、Gitやチャットに書きません。
停止は`./bin/stop_product.sh`です。デモのDBを複製・改名して本利用を始めません。
このlauncherはloopbackの導入準備用で、Django開発serverを使用します。
継続した寺務運用や複数端末での利用は、[運用前の確認](docs/operations.md)を先に行います。

## データを入れる前に

寺院情報、帳票文面、法要ルール・宗派差、利用者の権限を確認します。
旧DB/CSV等の実データは`private/inbox/`へ後から置き、Gitへ追加しません。
別の一時DBで取り込みを検証し、原本・件数・関係・履歴・backupを確認してから進めます。
詳細は[AIと進める移行](docs/data_migration_with_ai.md)を参照してください。
