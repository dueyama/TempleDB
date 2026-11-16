# 運用前の確認・バックアップ・更新

## 初版の位置付け

loopbackのデモと空SQLiteは、試用と導入準備の入口です。
寺務の継続運用では、利用者の権限、寺院情報・宗派差、端末故障時の復旧、backupの別保存先、
更新の担当を決めます。複数端末から使うserverにはHTTPSと正式なserver構成が必要です。
Django `runserver`をそのままLANやインターネットへ公開しません。

PostgreSQL / Gunicorn / Caddy / 自動起動のtemplateも含まれますが、
この初版が全組合せの実機受入済みであることを意味しません。
OS全体への導入、unitの操作、port・URL・DB roleの変更は対象を説明してから行います。
アプリ用DB roleに必要以上のsuperuser権限を与えません。

## SQLiteのバックアップ

1. 書込みを止めるため`./bin/stop_product.sh`を実行し、対象の製品processが停止したことを確認します。
2. `runtime/product/`のDBと設定、必要な`private/`資産を、別の非公開保存先へ保全します。
3. `runtime/product/product.env`等の設定は秘密として扱います。DBだけのコピーでは復旧に必要な設定が欠け得ます。
4. 保存時刻、アプリ版、ファイルhashと保存先を記録し、別の一時コピーで実際に復元・起動を確認します。
5. 確認後に元の運用を再開します。backupを公開repoやissueへ添付しません。

稼働中SQLiteのDBファイルだけを通常のcopyで保存すると、WAL等との組合せが不整合になり得ます。
停止できない運用にはSQLiteのbackup API等を使う別の検証済み手順が必要です。
復元試験は元のDBへ上書きせず、一時保存先と隔離設定で行います。

PostgreSQLでは`pg_dump`等のlogical backupと、別DBへの`pg_restore`検証を組にして設計します。
現在の他寺院のhostや保存先を流用せず、対応版・認証・保存期間・失敗通知を決めてから自動化します。

## アプリ更新

利用者の変更と、配布元の新しいsourceの差分を確認し、DB・設定・資産のbackupを先に取ります。
隔離コピーで新sourceのmaintenance試験と、製品DBのupgradeを確認します。
製品launcherは未適用migrationを見つけても自動適用せず停止します。
確認したschema変更だけを明示的に適用し、画面・履歴・backupを再確認して運用を再開します。

codeを旧版へ戻すことは、変更後のDBを旧schemaへ安全に戻す保証にはなりません。
schema変更がある場合は、切り戻し方針を事前に用意します。
