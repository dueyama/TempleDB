from __future__ import annotations

from django.contrib.auth.views import PasswordChangeView
from django.utils.http import url_has_allowed_host_and_scheme


class SafeNextPasswordChangeView(PasswordChangeView):
    def get_success_url(self) -> str:
        next_url = (self.request.POST.get("next") or self.request.GET.get("next") or "").strip()
        if next_url and url_has_allowed_host_and_scheme(
            next_url,
            allowed_hosts={self.request.get_host()},
            require_https=self.request.is_secure(),
        ):
            return next_url
        return super().get_success_url()
