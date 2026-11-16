import re

BANNER = (
    '<aside style="padding:10px;background:#dceeff;color:#142b44;text-align:center" '
    'role="note">架空データだけの試用デモです。実際の個人情報は入力しないでください。'
    'ログイン：demo / demo。変更はこのブラウザのセッション中だけ有効で、ログアウトすると初期状態に戻ります。'
    'Vercelの実行環境が変わると初期状態に戻ることがあります。</aside>'
).encode()


class DemoBannerMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if not response.streaming and response.get("Content-Type", "").startswith("text/html"):
            response.content = re.sub(rb"(<body\b[^>]*>)", lambda m: m[0] + BANNER, response.content, count=1)
            if response.has_header("Content-Length"):
                response["Content-Length"] = str(len(response.content))
        response["Cache-Control"] = "private, no-store"
        response["X-Robots-Tag"] = "noindex, nofollow"
        return response
