# Windows Native Demo

この手順は、Windows 11 ARM64上でTempleDBの合成デモを確認するための限定経路です。
PostgreSQL、Gunicorn、Caddy、HTTPS、Windows service、Firewall、Tailscaleには触れません。
継続運用や複数利用者が必要な場合は、Linux系server等の別の導入・受入が必要です。
WSL2の実機受入は未実施です。

## 現在の受入状態

2026-08-06にWindows 11 ARM64でSetup、Verify、loopback server、合成デモuserのログイン、
寺務ホームのHTTP応答まで成功し、統計ページが動作することをユーザーが画面で確認しました。
これは**合成デモ中核経路の限定受入**であり、Windows nativeの正式運用対応ではありません。

受入時、Codex隔離processの環境変数列挙とCodex内蔵browserにplatform固有の問題がありました。
環境変数の全列挙は共通sourceで廃止しましたが、その修正を含む次archiveはWindows実機で
再受入待ちです。内蔵browserが利用できない場合、HTTP確認だけで画面表示、PDF、印刷まで
受け入れたことにはしません。

## 前提

- Windows 11 ARM64
- standard GIL版のnative ARM64 CPython 3.13.x
- このスターターを通常のfolderへ展開済み
- 初回のPython依存downloadに使えるnetwork

## GitHubのソース版とアーカイブ版

コマンドはどちらも同じです。GitHubのソース版にはDBを同梱しません。
`MANIFEST.json`の`demo_seed_mode=dataset`と`PUBLIC_BUILD.json`がある版では、
Setupがmigrationと`load_demo_dataset`で架空データを読み込み、Windows専用の
`runtime/windows-demo/demo.sqlite3`を新規作成します。チェック成功後にだけ正式なDB名へ移します。
失敗した場合は一時DBを破棄し、Setupで再試行できます。

従来のアーカイブ版は同梱`runtime/demo.sqlite3`の識別を確認してコピーします。
同梱DBの欠落を理由に、勝手に新規データへ切り替えません。
どちらもSetupを再実行した際は既存のWindowsデモDBを保持し、架空データを再投入しません。
product識別のDBや、所有を確認できない作業フォルダは拒否します。

このソース版の初期化処理は、Mac上のPowerShellと架空SQLiteで検査しています。
Windows実機での今回の版の再受入、PDF・印刷等の確認は引き続き別です。

日本語や空白を含むpathも受入対象ですが、OneDrive等の同期中folderは最初の試験では避けます。

## Codexと実行する

Windows版Codexで、このスターターfolderを開きます。PowerShellの実行policyを恒久変更せず、
スターターrootから次を順番に実行します。

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\bin\windows_demo.ps1 -Action Setup
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\bin\windows_demo.ps1 -Action Verify
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\bin\windows_demo.ps1 -Action Start
```

ブラウザで `http://127.0.0.1:8011/` を開き、`demo` / `demo`でログインします。
serverは前面実行だけに限定しています。停止は起動したPowerShell windowで`Ctrl+C`を押します。

`-Python`を指定する場合は、standard GIL版のnative ARM64 CPython 3.13.xの
`python.exe`を絶対pathで渡します。

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\bin\windows_demo.ps1 -Action Setup -Python "C:\Path\To\python.exe"
```

## 撤去

次は、この展開folder内に生成した`.venv-windows-demo/`、
`runtime/windows-demo/`、およびそれらのownership / 排他記録だけを削除します。
起動中serverがあれば拒否します。
同梱原本`runtime/demo.sqlite3`、Python本体、machine全体の設定は変更しません。
共有の`runtime/`自体と、架空データloaderが作る`app/data/generated/`の参照ファイルは残します。
これらはMac/Linux側のデモと共用し得るため、Windows専用の削除対象には含めません。

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\bin\windows_demo.ps1 -Action Cleanup -ConfirmCleanup
```

## 安全境界

- `TEMPLEDB_DATABASE_ENGINE=sqlite`とdemo DBの絶対pathを毎回固定します。
- アーカイブ版は同梱`runtime/demo.sqlite3`を読取検証してから、Windows専用作業DBへcopyします。
  ソース版は同梱datasetから新規作成し、別に存在する`runtime/demo.sqlite3`は読み書きしません。
  migrationと起動は`runtime/windows-demo/demo.sqlite3`だけを対象にします。
- `DATABASE_*`、`PG*`、`OPENAI_*`、`GOOGLE_*`等のambient値を子processから除去します。
- Python launcherの自動installを無効にし、`app/pyproject.toml`から抽出した依存を
  workspace専用venvだけへ入れます。`app/`自体へbuild生成物を作りません。
- listenerは`127.0.0.1:8011`だけです。
- `runserver --noreload --nothreading`を使います。
- package manifest、dataset manifest、demo DB identity、migration、Django checkを起動前に確認します。
- link / junctionになっている固定pathでは実行または削除しません。
- setup / verify / start / cleanupは、内容を検証した専用lock fileで相互に排他実行します。
- 外側のownership marker、対象directory内のsentinel、directory生成時刻、所有tokenを照合し、
  同名の別directoryをcleanupしません。
- server guardにはPowerShellではなく実際のPython子processのPID・生成時刻・所有tokenを記録し、
  一致するguardだけを終了時に削除します。
- `Ctrl+C`後はPythonの自然終了を最大10秒待ち、終了しないprocessを即時強制終了しません。
  この場合はguardを残して次の操作を拒否します。
- cleanupはownership markerを確認し、生成directoryを削除できた後でmarkerを削除します。
- 現行Mac本番、PostgreSQL、product instance、private assetには接続しません。
