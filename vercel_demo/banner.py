import re

BANNER = (
    '<aside style="padding:10px;background:#dceeff;color:#142b44;text-align:center" '
    'role="note">架空データだけの試用デモです。実際の個人情報は入力しないでください。'
    'ログイン：demo / demo。変更はこのブラウザのセッション中だけ有効で、ログアウトすると初期状態に戻ります。'
    'Vercelの実行環境が変わると初期状態に戻ることがあります。</aside>'
).encode()

LOGIN_HINT = (
    '<div class="callout" style="margin-bottom:18px" role="note" aria-label="デモ用アカウント">'
    '<strong>架空データのデモ用アカウント</strong><p>'
    'ユーザー名：<code>demo</code><br>パスワード：<code>demo</code></p>'
    '<p>入力済みです。そのまま「ログイン」を押して試せます。</p></div>'
).encode()


class DemoBannerMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if not response.streaming and response.get("Content-Type", "").startswith("text/html"):
            response.content = re.sub(rb"(<body\b[^>]*>)", lambda m: m[0] + BANNER, response.content, count=1)
            if request.path == "/login/":
                response.content = response.content.replace(b'<form method="post">', LOGIN_HINT + b'<form method="post">', 1)
                if request.method == "GET":
                    for field in (b"username", b"password"):
                        response.content = response.content.replace(
                            b'name="' + field + b'"', b'name="' + field + b'" value="demo"', 1,
                        )
            if response.has_header("Content-Length"):
                response["Content-Length"] = str(len(response.content))
        response["Cache-Control"] = "private, no-store"
        response["X-Robots-Tag"] = "noindex, nofollow"
        return response
