# PDF Japanese fonts

Noto Sans JP / Noto Serif JP Regular / Bold, weights 400 / 700 static TrueType instances.
Bundled for server PDF embedding; not delivered as web fonts.

Sources retrieved 2026-09-19:
- https://github.com/notofonts/noto-cjk/raw/main/Sans/Variable/TTF/Subset/NotoSansJP-VF.ttf
- https://github.com/notofonts/noto-cjk/raw/main/Serif/Variable/TTF/Subset/NotoSerifJP-VF.ttf

Generation with fontTools (build-time only):
```
font = TTFont(source)
instantiateVariableFont(font, {"wght": weight}  # 400 or 700, inplace=True)
font.save(destination)
```
Keep OFL-NotoSans.txt and OFL-NotoSerif.txt with these files.
The bundled files must be included in code archives; no dependency on OS-installed fonts.
f04408f5c8b215d3a16898187e9c200630ee3cd9da90ff244de96618d432f004  apps/office/assets/fonts/NotoSansJP-Regular.ttf
4254e58a1cab88a247cd5d068e64dbb0752d8e71139766cbe55362a24738631c  apps/office/assets/fonts/NotoSerifJP-Regular.ttf
cd1488b5b46f218e0fc97bb00fc23d908a754fc52953e3139e86738baa94ea3e  apps/office/assets/fonts/NotoSansJP-Bold.ttf
26b01ab8f4201c8a73147f5ee43ed1d279d065240c705f426d06fc1a22fce6bc  apps/office/assets/fonts/NotoSerifJP-Bold.ttf

Bold instances have unique name-table IDs 1/2/3/4/6 so PDF font registration keeps weights distinct.
