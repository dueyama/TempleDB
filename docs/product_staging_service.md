# Linux製品Staging service template

この文書と隣接templateは、tenant operations packから作った
`product / staging`候補をLinuxで検証するための配布資料です。
既存の合成デモserviceとは別の名前、DB、port、workspace、OS userを使います。

templateは候補ごとの値をreviewしてから`/etc`への配置を行います。未置換のtemplateを
`systemctl enable/start`してはいけません。PostgreSQL candidateの接続許可は
専用activation commandだけで変更し、CaddyやTailscaleの入口変更とは分けます。

## 3つのroot

- `@WORKSPACE_ROOT@`: 同じGit commitのTempleDB Platformを含むworkspace
- `@TENANT_ROOT@`: pack applyで新規作成され、`.complete`が最後に公開された候補
- `@PRODUCT_STAGING_PROXY_ROOT@`: Caddy用設定と収集済みstaticだけを置くroot

app serviceは`@WORKSPACE_ROOT@/app`からcodeを読み、
`TEMPLEDB_TENANT_ROOT=@TENANT_ROOT@`で寺院固有設定を分離します。
Python環境は初回配置では`@WORKSPACE_ROOT@/.venv`を一つだけ作ります。app内部から別の
`manage.py` processを起動する処理も、現在動いている同じPython interpreterを
再利用するため、`@WORKSPACE_ROOT@/app/.venv`へのsymlinkは作りません。
通常のコード更新では、DBとtenant rootを作り直さず、新しいroot-owned workspaceを別pathへ
配置できます。Python依存契約が同一なら、rendererの`--runtime-python`へ直前releaseの
root-owned Pythonを指定し、全依存packageの再導入を省略します。serviceは
`python -m gunicorn`で新workspaceからcodeを読みます。
runtime Pythonはtenant / backup / proxy / environment pathと重ねません。serviceは設定された
Pythonを使う前に、固定`/usr/bin/python3 -I`でworkspace内のroot-owned verifierを実行し、
runtime Python本体、symlink実体、両方の親chainがroot所有・共有書込不可であることを確認します。
pack内の参照用環境snapshotはapp serviceの`EnvironmentFile`にせず、
配備先で新規作成する`@PRODUCT_STAGING_MACHINE_ENV@`だけにsecretと機械固有値を
記録します。

## fail-closedな環境順

app unitは次の順で環境fileを読みます。

1. `@PRODUCT_STAGING_MACHINE_ENV@`: 配備先で新規作成するowner-only machine profile
2. `@PRODUCT_STAGING_SAFETY_ENV@`: `env.product-staging-safety.in`からrenderする
   owner-only安全上書き

安全上書きは必ず最後です。ここでPostgreSQL、`runtime_kind=product`と組になる
`TEMPLEDB_RUNTIME_ROLE=staging`、絶対tenant root、local DB名、Google credentialの
空値、Staging専用backup rootを確定します。`staging` roleはGoogle Calendar、
日次backup、週次test restoreをapp内部でも停止します。
手動backup / test restoreだけは専用backup rootで確認できます。
`TEMPLEDB_TAILSCALE_SERVE=0`も
明示し、既存Tailscale設定を追加・変更・削除しません。

OpenAI OCRとmemo検索は、`@PRODUCT_STAGING_ALLOW_OPENAI@`を`1`へrenderし、
machine profileへ`OPENAI_API_KEY`を明示した場合だけStagingでも利用できます。
既定は`0`とし、Google Calendarの停止とは分離します。

machine profileには少なくとも強い`DJANGO_SECRET_KEY`、host / URL、
PostgreSQL passwordを記録します。OpenAIを試す場合だけAPI keyも記録します。
modeは0600、親directoryは0700とし、source machineの環境fileをコピーして流用しません。

DBの凍結解除・再凍結にだけ必要な`TEMPLEDB_TRANSFER_TARGET_*`は、3つ目の
root所有0600 `operator env`へ分離します。これはapp unitの`EnvironmentFile`に含めず、
Gunicornへ渡しません。`bin/run_product_staging_candidate_command.py`だけがroot権限で
3 fileを安全に読み、値を表示せず、全検証後にsupplementary group / GID / UIDを専用app userへ
落としてからmanagement commandを実行します。workspaceのDjango codeをrootでは実行しません。
candidate rootの期待owner UIDは別途固定し、新しいcontrol receiptだけをそのownerで作ります。
machine / safety / operator envの親directoryはroot所有0700にします。
runnerの操作先は`activate_tenant_operations_candidate`、
`verify_tenant_operations_candidate`、`deactivate_tenant_operations_candidate`の3 commandだけです。

配布workspace内の原本を`sudo`で直接実行してはいけません。workspace全treeをroot所有・
group/other書込不可にし、workspaceから`/`までの全親directoryもroot所有・共有書込不可・
symlinkなしにした後、SHA256を確認した原本を固定pathへinstallします。

```bash
sudo install -d -o root -g root -m 0755 /usr/local/libexec
sudo install -o root -g root -m 0755 \
  <ABSOLUTE_WORKSPACE>/bin/run_product_staging_candidate_command.py \
  /usr/local/libexec/templedb-product-staging-candidate-command.py
```

helper自身、全親directory、workspaceの全directory / file / safe symlink、venv、`manage.py`、
candidateの空のsealed `.env`をDjango起動前に検証します。固定`/usr/bin/python3`以外の
ambient interpreter、`PYTHONPATH`、loader制御key、unknown safety keyを受け付けません。
固定pathのhelperは起動ごとにworkspace内原本とのSHA256一致も再検証し、install後に片方だけが
変更された状態では操作を拒否します。
helperは`/usr/bin/python3 -I`で起動し、allowlist済みcomplete environmentを組み立ててから
app UIDへ権限縮小します。candidate `.env`は通常loaderでも読みますが、空であることをhelperが
直前に再確認し、machine値や秘密値はroot-only envから渡します。通常entrypointから使える
`.env`読込迂回flagは設けません。
operator passwordはruntime DB passwordと同じleast-privilege candidate owner資格に限定し、
別のsuperuser秘密をapp processへ渡す設計にはしません。

## activation gate

candidate DBはapply成功後も`ALLOW_CONNECTIONS=false`で凍結されているため、
serviceを開始する前に次の2段階を完了します。

1. activation commandが、candidate rootの`.complete`と
   `tenant-pack-apply.json`、archive SHA256、required Git commit、installation ID、
   PostgreSQL DB名 / OID / ownership token、`ALLOW_CONNECTIONS=false`、
   apply時のtenant policy / preferences / private / source registry / generated
   referenceの全mappingを再照合する。その同じOID / ownership tokenのDBだけを
   operatorの明示操作で接続許可し、owner-onlyのactivation receiptを作る。
2. 起動時read-only verifierがapply / activation receipt、archive / commit /
   installation、DB identity、`ALLOW_CONNECTIONS=true`を再照合する。sealed `.env`、policy、
   source registryとpackに含まれていたprivate assetは内容hashも確認する。ただし通常運用で
   PDF取込・移動が発生する郵便振込scan subtreeだけは可変とする。preferences、generated、
   runtime、新しいprivate fileと郵便振込scanは通常操作で増減できるが、symlink、特殊file、
   hardlink、group / other書込可能fileは拒否する。

activationはStaging roleとcandidate root / DB名の二重確認値を必須にする。実機では
management commandを直接起動せず、root-only envを分離したrunnerを使う。

```bash
sudo /usr/bin/python3 -I \
  /usr/local/libexec/templedb-product-staging-candidate-command.py activate \
  --workspace-root <ABSOLUTE_WORKSPACE> \
  --candidate-tenant-root <ABSOLUTE_TENANT_ROOT> \
  --run-user <PRODUCT_STAGING_USER> \
  --machine-env <ROOT_ONLY_MACHINE_ENV> \
  --safety-env <ROOT_ONLY_SAFETY_ENV> \
  --operator-env <ROOT_ONLY_OPERATOR_ENV> \
  --expected-git-commit <FULL_COMMIT> \
  --expected-archive-sha256 <PACK_SHA256> \
  --expected-installation-id <PRODUCT_INSTALLATION_ID> \
  --expected-database-name <CLONE_DATABASE_NAME>
```

runnerは確認値をmanagement commandの`--confirm-*`へ同じprocess内で渡す。machine envに
safety key、Python / loader制御key、transfer credentialが混ざっていれば拒否し、operator
envにtransfer以外のkeyがあっても拒否する。host / port / DB ownerはsafety envとoperator
envで一致し、loopback PostgreSQLだけを対象にする。
candidate owner roleはapply時にだけ一時的に`CREATEDB`を持たせ、apply後・activation前に
`NOCREATEDB`へ戻す。activationと起動時verifyは`LOGIN`でありながら
`NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS`、他roleとのmembershipなし、
candidate以外のDB所有なしを`pg_roles` / `pg_auth_members` / `pg_database`から再確認し、
権限や所有範囲が強いroleのままなら起動を拒否する。

app unitの`@ACTIVATED_CANDIDATE_VERIFIER@`は、さらにservice開始のたびに実行する
読み取り専用commandのplaceholderです。次のmanagement commandを
絶対pathで始まるcommand引数列へrenderし、
`.complete`、apply receipt、activation receipt、archive / commit / installation ID、
DB名 / OID / ownership token、tenant資産のdigest、`ALLOW_CONNECTIONS=true`を
再照合します。不一致なら非0で終了します。

```bash
<ABSOLUTE_PYTHON> <ABSOLUTE_APP_ROOT>/manage.py \
  verify_tenant_operations_candidate \
  --candidate-tenant-root <ABSOLUTE_TENANT_ROOT> \
  --expected-git-commit <FULL_COMMIT> \
  --expected-archive-sha256 <PACK_SHA256> \
  --expected-installation-id <PRODUCT_INSTALLATION_ID> \
  --expected-database-name <CLONE_DATABASE_NAME>
```

未置換のunitが`systemd-analyze verify`と起動を通らないことは、引き続き意図した
fail-closed動作です。template自体にはDBをthawするcommand、`migrate`を適用する
command、`collectstatic`、`runserver`を含めません。

実験終了時はapp / proxy serviceを停止し、接続0を確認できる状態で専用
deactivation commandを実行する。同じOID / ownership tokenのDBだけを
`ALLOW_CONNECTIONS=false`へ戻し、deactivation receiptを残す。以後の起動時
verifierはdeactivation済み候補を拒否する。

```bash
sudo /usr/bin/python3 -I \
  /usr/local/libexec/templedb-product-staging-candidate-command.py deactivate \
  --workspace-root <ABSOLUTE_WORKSPACE> \
  --candidate-tenant-root <ABSOLUTE_TENANT_ROOT> \
  --run-user <PRODUCT_STAGING_USER> \
  --machine-env <ROOT_ONLY_MACHINE_ENV> \
  --safety-env <ROOT_ONLY_SAFETY_ENV> \
  --operator-env <ROOT_ONLY_OPERATOR_ENV> \
  --expected-git-commit <FULL_COMMIT> \
  --expected-archive-sha256 <PACK_SHA256> \
  --expected-installation-id <PRODUCT_INSTALLATION_ID> \
  --expected-database-name <CLONE_DATABASE_NAME>
```

起動時read-only verifierは通常の`DATABASE_*`接続だけを使うため、operator envや
`TEMPLEDB_TRANSFER_TARGET_*`を必要としない。

## render契約

次のtokenは配備先固有値へ置換します。demoのservice名、DB名、
8011 / 8012など既存demo portを流用してはいけません。

- `@WORKSPACE_ROOT@`
- `@TENANT_ROOT@`
- `@RUN_USER@` / `@RUN_GROUP@`
- `@PROXY_USER@` / `@PROXY_GROUP@`
- `@PRODUCT_STAGING_MACHINE_ENV@`
- `@PRODUCT_STAGING_SAFETY_ENV@`
- `@PRODUCT_STAGING_BACKUP_ROOT@`
- `@PRODUCT_STAGING_PROXY_ROOT@`
- `@PRODUCT_STAGING_PROXY_STATE_ROOT@`
- `@PRODUCT_STAGING_DATABASE_NAME@`
- `@PRODUCT_STAGING_DATABASE_USER@`
- `@PRODUCT_STAGING_DATABASE_PORT@`
- `@PRODUCT_STAGING_POSTGRESQL_UNIT@`
- `@PRODUCT_STAGING_GUNICORN_PORT@`
- `@PRODUCT_STAGING_PROXY_PORT@`
- `@PRODUCT_STAGING_ALLOW_OPENAI@`（`0`または`1`）
- `@PRODUCT_STAGING_RUNTIME_PYTHON@`
- `@PRODUCT_STAGING_RUNTIME_PYTHON_VERIFIER@`
- `@ACTIVATED_CANDIDATE_VERIFIER@`

`bin/render_product_staging_service.py`はこれらをstrictに検証し、sudo、install、
activation、service startを行わず、未作成のowner-only出力rootへunit、safety env、
Caddyfile、SHA256付きrender manifestだけを生成する。出力をreviewしてから、別工程で
root所有の配置先へinstallする。raw `sed`でtokenを個別置換しない。

rootと環境fileはすべて絶対pathにし、demo workspace / DB / portと重ねません。
workspace、tenant、backup、proxy、proxy stateは相互に同一pathや親子pathにせず、machine / safety
envもそれらの配下へ置きません。backup rootをtenant rootと同一または配下にすると、systemdの
書込bindがtenant全体を可変にしてしまうためrendererが拒否します。
Platform workspace、machine / safety environment、activated verifier executableは
root管理とし、app実行userから書き換えられないようにします。environment fileは
systemdだけが読めるroot所有0600にします。

tenant rootはpack applyを行ったuserとapp実行userのownershipを一致させ、
backup rootもapp実行user専用の既存0700 directoryとして準備します。
apply時だけcandidateの未作成rootを作れるowner-only親directoryをapp userへ渡し、apply完了後・
activation前にその親directoryをroot所有0755へ固定します。candidate root自体はapp user所有0700の
ままにし、helperはcandidate / backup双方の親chainが`/`までroot所有・共有書込不可であることを確認します。
proxy rootのCaddyfileとstaticはroot管理のread-only、proxy state rootだけは
proxy実行user専用の既存0700 directoryにします。proxy用2 rootは
`ProtectHome=true`の外側（例: `/srv`と`/var/lib`）に置きます。service起動時にdirectory作成、
owner変更、static生成は行いません。appはPostgreSQLへloopback TCPで接続し、
PostgreSQL socket directoryをmount namespaceへ公開しません。

appとproxyはloopbackだけで待ち受けます。proxy unitは別userで動き、
Platform、tenant root、PostgreSQL socket、machine envを参照しません。
Caddyの書込み先もproduct Staging専用state rootへ限定し、demoや標準Caddyの
`/var/lib/caddy`を共有しません。
Caddy unitはTailscale serviceへ依存しないため、任意のTLS入口の有無とは別に
local healthを確認できます。対話操作には、machine profileで別途確認したHTTPS入口と
trusted originを用意します。

render後はsecretを表示しない方法でplaceholder残存、owner / mode、port競合、
unit差分をreviewし、`systemd-analyze verify`が成功することを確認します。
ただし、これはインストールや起動の許可ではありません。

## 起動前read-only contract

app unitは、次が全て成功した場合だけGunicornを
起動します。

1. 固定system Pythonによるruntime Pythonのroot-owned immutable path verifier
2. activated candidate verifier
3. local PostgreSQL readiness
4. `verify_runtime_contract --engine postgresql --runtime-kind product`
5. `migrate --check`
6. Django deploy check
7. 収集済み代表static fileの存在確認

tenant operations packを作成したsource commitと現在のruntime commitは別の意味を持つ。
初回は同一値だが、migration・依存・tenant assetを変えない通常コード更新では、rendererへ
`--expected-git-commit <source commit>`と
`--expected-runtime-git-commit <new runtime commit>`を分けて渡す。apply / activation receiptは
source commitの由来証跡として変更せず、現在workspaceだけをruntime commitで検証する。
render manifest version 1の`platform_commit`は従来どおりsource commitを表し、
`runtime_platform_commit`が現在起動するcommitを表す。
詳細は配布元TempleDB repositoryの`docs/runbooks/product_staging_code_update.md`を参照する。

boot時にDB作成、restore、migration適用、demo data投入、`collectstatic`は行いません。
GunicornとCaddyのaccess logはquery stringを記録せず、process生成後はloopbackの
login応答まで確認します。

別machineへ移した旧sourceの`LegacySource.file_path`が元machineの絶対pathを保持している
場合、activation後・初回service開始前に`normalize_legacy_source_paths`をまずdry-runする。
registry entry、file名、SHA256、実在fileが一致し、変更対象がlegacy mirrorの`file_path`
だけであることを確認した場合に限り、candidate DBで`--execute`する。source authorityは
引き続きregistry / `source_id`であり、この処理はMac Primaryへ実行しない。
