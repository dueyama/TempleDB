# 開発参加とAIによる変更

`AGENTS.md`と`docs/maintenance.md`を読み、再現手順と期待する動作を説明してください。
小さい変更に分け、既存の導線・業務仕様と利用者の独自変更を保全します。

- issue/PRには架空データを使い、個人情報・実帳票・秘密を載せません。
- service/use-caseとview、通常業務とsource adapterの境界を保ちます。
- 保存経路を変える場合は、業務更新と変更履歴の整合を確認します。
- `.venv/bin/python bin/test_maintenance.py`と変更箇所に必要な検証結果を書きます。
- migration変更は空DBだけでなく既存DBのupgradeを検証し、既存migrationを無断で書き換えません。
- 第三者コード・画像・font等を加える場合は、出典とlicenseを明記します。

本体への貢献は、本体のMITライセンスで再配布できる権利を持つ内容で行ってください。
third-partyの権利表示は維持します。テスト成功と本番・外部サービスの受入は区別します。
