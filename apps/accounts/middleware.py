"""When an admin has made two-step sign-in required (Account & security →
Security settings), someone signed in without it is sent to set it up before
anything else."""
from django.shortcuts import redirect
from django.urls import reverse

from .models import SecuritySettings

EXEMPT = ("/accounts/", "/static/", "/media/", "/i18n/", "/sw.js", "/manifest.webmanifest", "/offline/", "/favicon.ico", "/__debug__/")


class TwoFactorPolicyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and not request.path.startswith(EXEMPT):
            policy = SecuritySettings.objects.filter(pk=1).only("two_factor").first()
            if policy is not None and policy.requires_two_factor(user):
                from .twofactor import enabled_for

                if not enabled_for(user):
                    return redirect(reverse("two_factor_setup") + "?required=1")
        return self.get_response(request)
