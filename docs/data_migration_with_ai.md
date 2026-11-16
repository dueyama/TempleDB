# Codexと行う既存データ移行

## 目的

TempleDBは、異なる製品のDBを無確認で自動変換することを約束しません。Codexがsourceを調査し、ユーザーが業務上の意味を確認し、source専用adapterを作って安全に移行します。

移行先は `runtime_kind=product` の製品DBです。`runtime/demo.sqlite3` は見本専用で、移行先には使いません。

## 1. 原本を置く

ユーザーがMDB、CSV bundle、FileMaker export、SQL dumpなどを次へ置きます。

```text
private/inbox/<source-name>/
```

この場所はGit管理対象外です。原本を直接編集しません。passwordやcredentialが別途必要な場合もtracked fileへ書かず、Codexがユーザーと安全な受け渡し方法を確認します。

## 2. Read-only inventoryを作る

Codexは、利用可能なreaderを確認してからread-onlyで次を記録します。

- file名、形式、size、hash
- table / sheet / file一覧
- row count
- column名、型、null・blank、代表値のprofile
- primary key候補、relation候補、code値
- 文字encoding、日付・数値の表現
- 添付fileや外部参照の有無

sample rowには個人情報が含まれ得るため、公開docsやcommitへコピーしません。必要な確認はローカルで行い、記録には構造、件数、匿名化した例だけを残します。

## 3. Mappingを相談する

Codexはmapping候補を提示し、ユーザーへ業務上の意味を確認します。

特に確認が必要な例:

- 「戸主」「世帯」「家族」の境界
- 故人と現存人物の表現
- 戒名、法名、没年月日、享年
- 法要予定と実施済み記録
- 地区、役職、会費、案内送付のcode
- 同一人物・同一住所の重複判定
- 空欄、0、未設定、削除済みの違い

source固有の知識はadapterへ置き、寺院固有の表示・運用方針はtenant policyと分けます。

## 4. Adapterとtestを作る

adapterは少なくとも次を分けて読めるようにします。

- source reader
- raw/staging mapping
- canonical transformer
- source固有validation
- provenanceとerror summary

新しい本体ロジックを `app/apps/imports/services.py` や `app/apps/imports/views.py` へ追加しません。既存の共通import基盤とadapter境界を確認して配置します。

test fixtureには可能な限り人工データを使います。実データの行、氏名、住所、電話、memoをtracked fixtureへ入れません。

## 5. 製品DBとは別にdry-runする

最初の変換先は `runtime/product/templedb.sqlite3` ではありません。`runtime/migration-work/` などGit管理外の隔離領域にscratch DBを作り、繰り返し実行できるようにします。

dry-run reportには次を含めます。

- source別入力件数
- canonical model別出力予定件数
- 除外・補正・保留件数と理由
- relation解決件数、孤立行
- 重複候補
- parse/validation error
- ユーザーが選んだ代表レコードのbefore/after
- 再実行して同じ結果になること

source rowと出力rowのprovenanceを追えるようにし、黙って値を落としません。

## 6. ユーザー確認後に投入する

Codexはdry-run結果を要約し、未確定事項を残したまま進めません。ユーザー承認後に次を行います。

1. 現在の製品DBをbackupする
2. backupを別DBへテスト復元する
3. 対象adapterとsource snapshotを固定する
4. 製品DBへ投入する
5. 件数、relation、constraint、代表レコードを再照合する
6. error・除外・補正の監査記録を保存する
7. 新しいbackupとテスト復元を確認する

失敗時は途中状態を通常運用へ渡さず、backupから戻せることを確認します。大きな移行では、空製品DBを作り直して再投入する方が安全な場合もあります。

## 7. AIが続きを保守できる状態を残す

移行完了後は、実データを含めず次を残します。

- source形式とadapter owner
- mapping判断とユーザー確認事項
- validation rule
- 実行commandとversion
- aggregate件数とerror summary
- backup / restore確認結果
- adapterのtest

これにより、次のCodexも同じフォルダから安全に保守を続けられます。
