"""Quick-add ("+" beside a dropdown): create a category, source or member
from a popup without leaving the form you're filling in.

Each kind reuses the app's own ModelForm, so validation is identical to the
full create page. The endpoint answers in JSON; the popup script adds the new
option to the dropdown and selects it.
"""

from dataclasses import dataclass
from importlib import import_module

from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.translation import gettext as _, gettext_lazy
from django.views.decorators.http import require_POST


@dataclass(frozen=True)
class QuickCreateKind:
    form_path: str          # "apps.expense.forms.ExpenseCategoryForm"
    model_path: str         # "apps.expense.models.ExpenseCategory"
    title: str              # popup heading
    noun: str               # used in tooltips/messages ("category")

    def _load(self, path):
        module, name = path.rsplit(".", 1)
        return getattr(import_module(module), name)

    @property
    def form_class(self):
        return self._load(self.form_path)

    @property
    def model(self):
        return self._load(self.model_path)


KINDS = {
    "expense_category": QuickCreateKind(
        "apps.expense.forms.ExpenseCategoryForm", "apps.expense.models.ExpenseCategory",
        gettext_lazy("New expense category"), gettext_lazy("category"),
    ),
    "income_source": QuickCreateKind(
        "apps.income.forms.IncomeSourceForm", "apps.income.models.IncomeSource",
        gettext_lazy("New income source"), gettext_lazy("income source"),
    ),
    "household_category": QuickCreateKind(
        "apps.household.forms.HouseholdCategoryForm", "apps.household.models.HouseholdCategory",
        gettext_lazy("New bazar category"), gettext_lazy("category"),
    ),
    "household_member": QuickCreateKind(
        "apps.household.forms.HouseholdMemberForm", "apps.household.models.HouseholdMember",
        gettext_lazy("New household member"), gettext_lazy("member"),
    ),
}


def form_prefix(kind):
    return f"qa_{kind}"


def get_kind(kind):
    try:
        return KINDS[kind]
    except KeyError:
        raise Http404("Unknown quick-add kind")


def popup_context(kind):
    """Everything the popup template needs for one kind."""
    spec = get_kind(kind)
    return {
        "kind": kind,
        "form": spec.form_class(prefix=form_prefix(kind)),
        "url": reverse("quick_create", args=[kind]),
        "title": spec.title,
        "noun": spec.noun,
    }


def _ok(obj, message, status=200):
    return JsonResponse({"ok": True, "id": obj.pk, "name": str(obj), "message": message}, status=status)


@login_required
@require_POST
def quick_create_view(request, kind):
    spec = get_kind(kind)
    owned = spec.model.objects.filter(user=request.user)

    # Second step of the "it exists but is inactive" flow.
    reactivate_id = request.POST.get("reactivate")
    if reactivate_id:
        obj = get_object_or_404(owned, pk=reactivate_id)
        obj.is_active = True
        obj.save(update_fields=["is_active"])
        return _ok(obj, _("'%(name)s' is active again and selected.") % {"name": obj})

    form = spec.form_class(request.POST, prefix=form_prefix(kind))
    if not form.is_valid():
        errors = {field: [str(e) for e in errs] for field, errs in form.errors.items()}
        return JsonResponse({"ok": False, "errors": errors}, status=400)

    name = form.cleaned_data["name"].strip()
    existing = owned.filter(name__iexact=name).first()
    if existing and existing.is_active:
        # Don't create a duplicate — just pick the one that's already there.
        return _ok(existing, _("'%(name)s' already exists, so it's been selected.") % {"name": existing})
    if existing:
        return JsonResponse({
            "ok": False,
            "errors": {"name": [_("'%(name)s' already exists but is inactive.") % {"name": existing}]},
            "reactivate": {"id": existing.pk, "name": str(existing)},
        }, status=409)

    obj = form.save(commit=False)
    obj.user = request.user
    obj.name = name
    obj.save()
    return _ok(obj, _("'%(name)s' added and selected.") % {"name": obj}, status=201)
