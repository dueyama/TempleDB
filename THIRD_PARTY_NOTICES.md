# Third-party assets and dependencies

本体独自コード・文書のMIT Licenseと、以下の第三者資産の利用条件は別です。

## 日本語PDF font

`app/apps/office/assets/fonts/`に、Noto Sans JP / Noto Serif JPのRegular/Boldを同梱します。
出典、静的TrueTypeへの生成方法、hashは同directoryのREADMEに記載されています。
OFL文`OFL-NotoSans.txt` / `OFL-NotoSerif.txt`をfontと一緒に保持してください。
OSのfont導入に依存せず、日本語PDFへ埋め込むための資産です。

## Python依存

`app/pyproject.toml`と`app/config/dependencies/`に依存範囲と固定版を記載しています。
Django、PDF/画像、Google API、数値処理等の依存packageには、それぞれ独自のlicenseがあります。
このMIT Licenseでそれらを再ライセンスするものではありません。
依存はsetup時に取得し、仮想環境やthird-partyのwheelをこのrepositoryへ同梱しません。

## デモ資産

`datasets/synthetic_demo_v1/`は架空データであり、実データの抜粋ではありません。
sample PDFは合成デモであることを本文に表示し、metadataのauthor/creatorも匿名です。
アイコンはTempleDBの追跡資産です。公開準備では画像metadataとfontの名前・license情報も確認し、
検査した資産のhashを固定します。第三者の権利が判明した場合は、その条件を別途確認します。
この候補全体の公開準備が完了するまでは外部へ再配布しません。
