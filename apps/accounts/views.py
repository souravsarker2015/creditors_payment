from django.conf import settings
from django.shortcuts import render, redirect
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib import messages
from django.http import HttpResponse, HttpResponseRedirect
from django.urls import reverse
from django.utils import translation
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from .models import AccentTheme, BackgroundTheme, Language, ThemeMode, UserProfile

def signup_view(request):
    if request.method == "POST":
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, _("Account created successfully!"))
            return redirect("dashboard")
    else:
        form = UserCreationForm()
    return render(request, "accounts/signup.html", {"form": form})

def login_view(request):
    if request.method == "POST":
        form = AuthenticationForm(data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            profile, _created = UserProfile.objects.get_or_create(user=user)
            translation.activate(profile.language)
            messages.success(request, _("Welcome back, %(username)s!") % {"username": user.username})
            response = redirect("dashboard")
            response.set_cookie(settings.LANGUAGE_COOKIE_NAME, profile.language)
            return response
    else:
        form = AuthenticationForm()
    return render(request, "accounts/login.html", {"form": form})

def logout_view(request):
    logout(request)
    messages.info(request, _("You have been logged out."))
    return redirect("login")


@login_required
@require_POST
def update_preferences_view(request):
    """Persist theme/accent/background/language to the user's profile.

    Any of the four fields may be posted; only the ones present are
    updated. A language change also activates the new language for this
    response and sets the language cookie Django's LocaleMiddleware reads,
    so the redirect below re-renders fully translated.
    """
    profile, _created = UserProfile.objects.get_or_create(user=request.user)

    theme_mode = request.POST.get("theme_mode")
    accent = request.POST.get("accent")
    background = request.POST.get("background")
    language = request.POST.get("language")

    if theme_mode in ThemeMode.values:
        profile.theme_mode = theme_mode
    if accent in AccentTheme.values:
        profile.accent = accent
    if background in BackgroundTheme.values:
        profile.background = background
    if language in Language.values:
        profile.language = language
        translation.activate(language)

    profile.save()

    # Theme/accent/background-only changes are fired from JS as a background request —
    # the toggle already applied itself instantly client-side, so there's
    # nothing to re-render. A language change needs a real navigation
    # because translated strings are resolved server-side.
    if request.headers.get("X-Preferences-Fetch") == "1" and language not in Language.values:
        return HttpResponse(status=204)

    next_url = request.POST.get("next") or request.META.get("HTTP_REFERER") or reverse("dashboard")
    response = HttpResponseRedirect(next_url)
    if language in Language.values:
        response.set_cookie(settings.LANGUAGE_COOKIE_NAME, language)
    return response
