# 環境と受入範囲

## 使いたい環境へ、AIと一緒に広げる

TempleDBはPython / DjangoのWebアプリです。必要なPythonとライブラリを用意できる環境なら、
AIと依存関係・起動方法を調整し、使える環境を広げていけます。
下の動作確認実績を出発点に、別のLinux、Windows x64、自分のサーバーなどへの導入も試してください。

使いたい端末のOS・CPU・Python版をAIに伝え、README・START_HERE.md・AGENTS.mdを読んでもらいます。
依存ライブラリの対応版や代替手順を調べ、架空データで初期化・起動・ログインまで確認しながら進めます。
調整した内容と成功したコマンドを残すことで、その環境での保守や次の導入にもつなげられます。

## 確認済みの出発点

2026-11-17時点の[CI実行結果](https://github.com/dueyama/TempleDB/actions/runs/44020019077)です。
sourceのmetadataはPython 3.13以上、Django 5.2系を前提とします。

| 環境・経路 | 確認した内容 |
|---|---|
| macOS 15 / Ubuntu 24.04 | 新規Setup、隔離保守試験、HTTPログイン・ホーム・戸主一覧・サーバー終了。Vercelデモの将来日付・保存・初期化・ブラウザ分離・独立worker認証も検査 |
| Windows 11 ARM64 native | ARM64 CPython 3.13でSetup・Verify・隔離保守・HTTPログイン/主要画面・終了・Cleanup。WSLを使わず実行 |
| Vercelの架空デモ | Django 5.2.19でログイン・保存・変更履歴・ログアウト後の再生成を実画面で確認 |
| 空SQLiteでの導入準備 | product識別、業務27表0件、二重初期化拒否、デモ不変を検査。管理者は利用者が別に作成 |

依存の固定版は`app/config/dependencies/`にあります。Windows nativeは専用の導入経路を使います。
WSL2・Windows x64・ほかのOS/CPUでは、この確認済み手順を参考にAIと導入条件を調べて試せます。
その環境で実際に確認できた範囲は、新しい実行記録として残してください。

## 日々の運用へ進めるとき

ローカルの標準launcherは、loopback接続の導入準備用です。
サーバーで継続運用する場合は、利用環境に合わせてHTTPS・自動起動・権限・backup/復旧を整えます。
PostgreSQL、実際のプリンター、外部サービス連携も、使う構成で確認しながら導入してください。
詳しくは[運用前の確認](operations.md)を参照してください。

この初版はGitHub向けのソース雛形です。OS/Python自体の導入や、別形式のarchive配布はそれぞれの手順で確認します。
