from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _

from . import services
from .forms import ZakatForm
from .models import GOLD_NISAB_G, SILVER_NISAB_G, ZakatSettings


@login_required
def zakat_view(request):
    settings, _created = ZakatSettings.objects.get_or_create(user=request.user)
    if request.method == "POST":
        form = ZakatForm(request.POST, instance=settings)
        if form.is_valid():
            obj = form.save(commit=False)
            sheet = services.sheet(request, obj)
            obj.skip = [l.key for l in sheet.lines if l.auto and request.POST.get(f"count_{l.key}") != "1"]
            obj.save()
            messages.success(request, _("Saved. The helper remembers your prices and choices for next time."))
            return redirect("zakat")
    else:
        form = ZakatForm(instance=settings)
    sheet = services.sheet(request, settings)
    return render(request, "zakat/zakat.html", {
        "form": form, "sheet": sheet, "has_farm": any(l.key.startswith("farm_") for l in sheet.lines),
        "gold_nisab_g": GOLD_NISAB_G, "silver_nisab_g": SILVER_NISAB_G,
        "auto_lines": [{"key": l.key, "amount": float(l.full if l.full is not None else l.amount), "side": l.side,
                        "on": l.key not in settings.skip, "farm": l.full is not None}
                       for l in sheet.lines if l.auto],
    })
