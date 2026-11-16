# 環境と受入範囲

sourceのmetadataはPython 3.13以上、Django 5.2系を前提とします。
依存の固定版は`app/config/dependencies/`にあり、Mac/Linux向けの固定をWindowsへ流用しません。

| 経路 | 初版候補の扱い |
|---|---|
| macOS ARM64の架空SQLiteデモ | Python 3.13.12で新規venvへの依存取得、デモ初期化、ログイン・ホーム表示を2026-11-16に確認 |
| Linux / WSL2の架空SQLiteデモ | 起動経路とCIの対象。各OSの実機受入とCIを区別 |
| 空SQLiteでの導入準備 | product識別、27表0件、二重初期化拒否、デモ不変を確認。管理者は利用者が別に作る。loopbackの開発serverとして扱う |
| PostgreSQLの正式server運用 | 専用の導入・backup・復旧・HTTPS・自動起動の受入が必要 |
| Windows native | `bin/windows_demo.ps1`の限定的な合成デモ。正式server運用の対応ではない |

WindowsはWindows 11 ARM64 + native ARM64 CPython 3.13が対象です。2026-08-06に別版の
Setup・Verify・ログイン・ホーム・統計の中核経路を限定受入しています（WSL経由ではありません）。
このソース候補は同梱DBを必要とせずdatasetから初期化します。今回のMac上のPowerShell検査は
DB初期化・保護の検査であり、Windowsの依存取得・server・停止・PDF・印刷・Cleanupの再受入とは分けます。
Windows x64は、この専用入口の受入対象に含めていません。

過去の別版・別端末の成功を、この候補の全面的な対応証明としません。
既存のPythonを使った新規venvでの確認であり、PythonやOS自体の導入からの受入ではありません。
公開先でのCI、Linux / WSL2 / Windowsの現候補の実機受入は未実施です。
CI定義はUbuntu/macOSとWindows ARM64を対象にします。LinuxのCI成功をWSL2実機の受入とは扱いません。
この初版はGitHub向けソース雛形の候補で、別形式のarchiveの配布・展開受入は含みません。
