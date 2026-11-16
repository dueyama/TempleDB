# PostgreSQLデモの常駐運用実験

この手順は、Linux / Raspberry Pi上の合成データ専用PostgreSQLデモを、
Gunicorn + Caddy + systemdで再起動後も利用できるか確認する実験です。
標準デモは引き続きSQLiteであり、製品DBやMacの起動設定を変更しません。

## 前提

- `TEMPLEDB_DEMO_MODE=1`
- `TEMPLEDB_ALLOW_POSTGRESQL_DEMO=1`
- `TEMPLEDB_DATABASE_ENGINE=postgresql`
- local PostgreSQLと`templedb_demo_*`名のDB
- `runtime_kind=demo`
- ownerだけが読める`.env.postgresql-demo`
- ownerだけが読める`.env.formal-server`
- Gunicornは`127.0.0.1:8012`
- Caddyは`127.0.0.1:8011`
- Tailscale Serve HTTPSは`http://127.0.0.1:8011`をproxyする
- CaddyはGunicorn / DB ownerとは別のOS userで動かし、`.env`、workspace、
  PostgreSQL socketを読めないようにする。書き込みはpackage標準の
  `/var/lib/caddy`だけに限定する

起動時にはDB作成、`migrate --noinput`、`load_demo_dataset`を行いません。
実効DB engineと`runtime_kind=demo`、PostgreSQLの接続、未適用migration、
Django deploy check、収集済み静的ファイルの確認が
成功した場合だけ
Gunicornを開始します。

`.env.formal-server`は標準デモarchiveへ秘密を埋め込まないため、
配備先で作成します。最低限、強い`DJANGO_SECRET_KEY`、
`DJANGO_DEBUG=0`、`TEMPLEDB_TRUSTED_PROXY_HTTPS=1`を設定し、
mode 600にします。trusted proxy HTTPSはCaddyをloopbackだけで待ち受けさせ、
Caddyが`X-Forwarded-Proto: https`を上書きするこの構成に限って有効にします。
tailnet hostname配下全体とpreload listはアプリが保証しないため、
includeSubDomains / preloadは有効にしません。対応するDjango warningだけは
この明示modeで意図的に抑止します。

systemdでは`EnvironmentFile`がunit内の`Environment=`より強いため、
DB engineをinline指定に頼りません。PostgreSQL unitは
`.env.demo` → `.env.formal-server` → `.env.postgresql-demo`の順で読み、
DB専用値を最後に確定します。SQLite fallbackは
`systemd/env.sqlite-demo-service.in`からrenderしたowner-only
`.env.sqlite-demo-service`を最後に読み、SQLite engine、絶対path、空のPostgreSQL値を確定します。

`collectstatic --noinput`は配備時やcode更新時に明示して1回実行します。
収集結果はroot管理のproxy専用directoryへcopyし、Caddyにはそのread-only copyだけを見せます。
boot時にはファイル生成をせず、faviconと代表CSSがなければfail closedにします。
Gunicornのaccess logはquery stringを記録せず、methodとpathだけをjournaldへ残します。
systemdがactiveになる前にloopbackのlogin応答まで待ち、単にprocessが生成されたことだけを
起動成功とはみなしません。これはGunicornとCaddyの両unitで確認します。
不要なGunicorn control socketも作りません。

## unitの作成

`systemd/*.service.in`の次のtokenを、実際の絶対pathと非root実行user/groupへ置換します。

- `@WORKSPACE_ROOT@`
- `@RUN_USER@`
- `@RUN_GROUP@`
- `@PROXY_ROOT@`
- `@PROXY_USER@`
- `@PROXY_GROUP@`

`systemd/env.sqlite-demo-service.in`では`@WORKSPACE_ROOT@`も置換し、
`.env.sqlite-demo-service`をmode 600でworkspace直下へ置きます。
render後は、内容と差分を確認してから`systemd-analyze verify`を実行します。
`Caddyfile.postgresql-demo`をunit外で手動検証する場合は、unitが渡す次の4変数も同時に指定します。

```bash
sudo -u caddy env \
  TEMPLEDB_PROXY_HOST=127.0.0.1 \
  TEMPLEDB_PROXY_PORT=8011 \
  TEMPLEDB_STATIC_ROOT=/var/lib/templedb-postgresql-demo-proxy/static \
  TEMPLEDB_GUNICORN_UPSTREAM=127.0.0.1:8012 \
  caddy validate \
  --config /var/lib/templedb-postgresql-demo-proxy/Caddyfile \
  --adapter caddyfile
```

変数なしの手動検証では`root` directiveの引数が空になり、正しいCaddyfileでも検証が失敗します。
unitの設置・有効化は機械全体への変更なので、ユーザーの明示許可と
`runtime/environment_changes.md`への記録が必要です。
Caddy packageの標準`caddy.service`はこの構成では使いません。導入後に
disabled / inactiveであることと、未管理の80番listenerがないことを確認します。
専用proxy unitだけをenabledにします。

通常は次の2 unitだけをenabledにします。

- `templedb-postgresql-demo.service`
- `templedb-postgresql-demo-proxy.service`

`templedb-sqlite-demo.service`はPostgreSQLから戻す場合の正式なGunicorn退路であり、
通常時はinstalled / disabled / inactiveにします。PostgreSQL unitと相互に
`Conflicts`を持つため、同じportへ同時起動しません。SQLiteへ戻してもCaddyと
Tailscale HTTPSの入口は変えません。

## 停止・切替・撤去

停止はproxy、稼働中のGunicornの順に行います。

PostgreSQLからSQLiteへ戻す場合は、元SQLiteのhashとidentityを確認してから、
次の順で実際のprocessも切り替えます。DB変換や再投入はしません。

```bash
sudo systemctl disable --now templedb-postgresql-demo.service
sudo systemctl enable --now templedb-sqlite-demo.service
systemctl is-active templedb-postgresql-demo.service
systemctl is-active templedb-sqlite-demo.service
```

SQLiteがactive、PostgreSQL Gunicornがinactiveで、HTTP表示とSQLite hashが正常なことを
確認します。PostgreSQLへ戻す場合は逆順です。

```bash
sudo systemctl disable --now templedb-sqlite-demo.service
sudo systemctl enable --now templedb-postgresql-demo.service
```

撤去時は3 unitを`disable --now`し、設置したunit fileだけを削除して
`systemctl daemon-reload`と`systemctl reset-failed`を実行します。
PostgreSQL DB、role、`.env`、元のSQLiteファイル、backupは自動削除しません。

## 受入確認

- PostgreSQL、Tailscale、PostgreSQL Gunicorn、Caddyがenabledかつactive
- SQLite fallbackはdisabledかつinactive
- 5432、8012、8011が想定どおりloopbackで待ち受ける
- 8012のPIDがGunicorn unit、8011のPIDがCaddy unitのMainPIDと一致
- DB identityが`demo`で、主要件数とmigration件数が導入前後で不変
- 元のSQLiteファイルのSHA256が不変で、どのprocessからも開かれていない
- `http://127.0.0.1:8011/login/`とTailscale HTTPSが応答
- `/static/icons/favicon.ico`が200
- `/static/office/schema_map.css`が200
- Django deploy checkがwarning 0件
- session cookieはSecure / HttpOnly / SameSite、CSRF cookieはSecure / SameSite
- HTTPS応答に短期HSTS、nosniff、same-origin referrer policyがある
- journalに再起動loop、SQLite fallback、デモ再投入、migration適用がない
- Gunicorn access logにquery stringがない
- stock `caddy.service`はdisabled / inactiveで、専用proxyだけが8011を待ち受ける

再起動試験ではboot IDが変わったことも記録します。
