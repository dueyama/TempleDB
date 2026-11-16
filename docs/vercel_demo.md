# Vercelでの試用デモ

`vercel_demo/`とrootの`vercel.json`は、Vercel上で架空データを試すための専用入口です。
ローカルの通常デモは従来どおり`bin/setup.sh`と`bin/run_demo.sh`を使います。

VercelではGitHub repositoryを取り込み、root directoryはrepositoryの先頭、frameworkはDjangoを選びます。
このデモ用コードを含むbranchを対象にします。専用の`DJANGO_SECRET_KEY`を暗号化環境変数へ設定します。
Python 3.13と既存のruntime依存版を使い、buildで架空JSONからseedを新規生成します。
実DB・既存.env・backup・Google/OpenAIの認証情報を渡す必要はありません。

ログインは`demo` / `demo`です。ブラウザの署名cookieごとに一時copyを使い、変更履歴もそのcopyへ保存します。
元seedは変更しません。Vercelの実行環境が変わると編集内容が初期状態へ戻ることがあります。
実際の個人情報・秘密を入力せず、日常業務のデータ保存には使わないでください。

この試用デモは、本運用のserver対応・永続保存・製品用のtenant分離の受入を意味しません。
Vercelの通常のpreview保護を維持して確認できます。GitHubをPrivateからPublicへ変更する必要もありません。
