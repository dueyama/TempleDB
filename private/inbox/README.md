# Private source inbox

既存システムから移行するMDB、CSV、FileMaker export、SQL dumpなどを、導入先でこのフォルダの下へ置きます。

- 配布パッケージには実データを同梱しません。
- このREADME以外はGit管理対象外です。
- 原本を直接編集せず、変換物は `private/work/` または `runtime/migration-work/` へ作ります。
- credentialやpasswordをこのREADMEやtracked fileへ書きません。
- Codexは内容をread-onlyで調査し、adapter、dry-run、ユーザー確認を経てから製品DBへ移行します。
