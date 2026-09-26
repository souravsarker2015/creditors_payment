"""Reusable pages for master data (species, ponds, markets, suppliers…).

One `Master` describes a kind of record; it provides the list (with search,
In use / Deleted tabs), add/edit, soft delete and restore views plus their
URLs. Each app only supplies a model, a form and a row template, so every
master-data page behaves the same way.

It also holds the business "+ Add new" popups (QUICK_ADD): a dropdown in any
business form can create the related record without leaving the page.
"""
from dataclasses import dataclass, field

from django import forms
from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path, reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from .decorators import business_access_required


# ── Forms ───────────────────────────────────────────────────────────────────

class BusinessForm(forms.ModelForm):
    """ModelForm for a business record.

    * `layout`: rows of field names for the shared form page; a row of two
      sits side by side, ("#", _("Title")) starts a new card with a title.
    * `unique_name`: fields that must not repeat (case-insensitive) within the
      business among records that aren't deleted.
    * Widgets get the app's input styling; date fields get the date picker.
    """

    layout = ()
    unique_name = ("name",)

    def __init__(self, *args, business, **kwargs):
        super().__init__(*args, **kwargs)
        self.business = business
        for name, f in self.fields.items():
            w = f.widget
            if isinstance(w, (forms.CheckboxInput, forms.RadioSelect, forms.CheckboxSelectMultiple)):
                continue
            if isinstance(w, forms.DateInput):
                w.format = "%Y-%m-%d"
                w.attrs.setdefault("class", "form-input datepicker")
                w.attrs.setdefault("autocomplete", "off")
            elif isinstance(w, forms.Textarea):
                w.attrs.setdefault("class", "form-input")
                w.attrs["rows"] = 2
            else:
                w.attrs.setdefault("class", "form-input")
            if isinstance(w, forms.NumberInput):
                w.attrs.setdefault("inputmode", "decimal")
                w.attrs.setdefault("step", "any")
        if self.instance.pk:  # "20" and "1450" rather than "20.000" and "1450.00"
            for name, f in self.fields.items():
                value = getattr(self.instance, name, None)
                if isinstance(f, forms.DecimalField) and value is not None and self.add_prefix(name) not in self.data:
                    self.initial[name] = format(value.normalize(), "f")
        for name, f in self.fields.items():
            qs = getattr(f, "queryset", None)
            model = getattr(qs, "model", None)
            if model is not None and hasattr(model, "business_id") and hasattr(model, "all_objects"):
                f.queryset = qs.filter(business=business)

    def rows(self):
        """The layout as [(title, [bound fields])] for the template."""
        out, current = [], []
        for row in self.layout or [(n,) for n in self.fields]:
            if isinstance(row, tuple) and row and row[0] == "#":
                out.append({"title": row[1], "fields": []})
                continue
            names = (row,) if isinstance(row, str) else row
            fields = [self[n] for n in names if n in self.fields]
            if fields:
                if not out:
                    out.append({"title": "", "fields": []})
                out[-1]["fields"].append(fields)
        return out

    def clean(self):
        data = super().clean()
        model = self._meta.model
        for name in self.unique_name:
            value = data.get(name)
            if not value:
                continue
            clash = model.objects.filter(business=self.business, **{f"{name}__iexact": value.strip()}).exclude(pk=self.instance.pk)
            if clash.exists():
                self.add_error(name, _("“%(value)s” already exists.") % {"value": value})
        return data


def money_field(f, affix="৳"):
    """Mark a field so the business field partial shows a ৳ (or other) prefix."""
    f.affix = affix
    return f


# ── Master pages ────────────────────────────────────────────────────────────

@dataclass
class Master:
    name: str                       # URL name, e.g. "species" → business:species, business:species_add …
    model: type
    form_class: type
    title: str
    subtitle: str
    add_label: str
    row_template: str
    view_cap: str | None = None
    edit_cap: str = "manage_settings"
    search_fields: tuple = ("name",)
    select_related: tuple = ()
    prefetch: tuple = ()
    cards: bool = False
    icon: str = "list"
    empty_title: str = ""
    empty_text: str = ""
    form_template: str = "business/master/form.html"
    list_template: str = "business/master/list.html"
    formset_class: type | None = None       # inline rows, e.g. a market's deductions
    formset_title: str = ""
    formset_template: str = ""
    filters: list = field(default_factory=list)   # [(key, label, Q)] extra tabs
    base_filter: object = None      # Q: this page only shows these rows (e.g. suppliers)
    group: object = None            # fn(objects) -> [(label, objects)]
    annotate: object = None         # fn(queryset, business) -> queryset
    decorate: object = None         # fn(objects, business) -> None (add computed attrs)
    delete_check: object = None     # fn(obj) -> error message or None
    initial: object = None          # fn(request) -> dict for a new record
    after_save: object = None       # fn(obj, request)
    form_context: object = None     # fn(request) -> extra context for the form page
    nav_template: str = ""          # tabs shown above the list (e.g. the Feed section's tabs)

    # views -------------------------------------------------------------------
    def urls(self):
        guard = business_access_required
        return [
            path("", guard(capability=self.view_cap)(self.list_view), name=self.name),
            path("add/", guard(capability=self.edit_cap)(self.form_view), name=f"{self.name}_add"),
            path("<int:pk>/edit/", guard(capability=self.edit_cap)(self.form_view), name=f"{self.name}_edit"),
            path("<int:pk>/delete/", guard(capability="delete")(require_POST(self.delete_view)), name=f"{self.name}_delete"),
            path("<int:pk>/restore/", guard(capability="delete")(require_POST(self.restore_view)), name=f"{self.name}_restore"),
        ]

    def _qs(self, business, deleted=False):
        manager = self.model.all_objects if deleted else self.model.objects
        qs = manager.filter(business=business, is_deleted=deleted)
        if self.base_filter is not None:
            qs = qs.filter(self.base_filter)
        if self.select_related:
            qs = qs.select_related(*self.select_related)
        if self.prefetch:
            qs = qs.prefetch_related(*self.prefetch)
        if self.annotate:
            qs = self.annotate(qs, business)
        return qs

    def list_view(self, request):
        b = request.business
        show = request.GET.get("show", "")
        q = request.GET.get("q", "").strip()
        qs = self._qs(b, deleted=show == "deleted")
        tab = next((f for f in self.filters if f[0] == show), None)
        if tab:
            qs = qs.filter(tab[2])
        if q:
            cond = Q()
            for f in self.search_fields:
                cond |= Q(**{f"{f}__icontains": q})
            qs = qs.filter(cond).distinct()
        objects = list(qs[:500])
        if self.decorate:
            self.decorate(objects, b)
        alive = self._qs(b)
        tabs = [{"key": "", "label": _("All"), "count": alive.count()}]
        tabs += [{"key": k, "label": label, "count": alive.filter(cond).count()} for k, label, cond in self.filters]
        deleted_count = self._qs(b, deleted=True).count()
        if deleted_count or show == "deleted":
            tabs.append({"key": "deleted", "label": _("Deleted"), "count": deleted_count})
        return render(request, self.list_template, {
            "m": self, "objects": objects, "groups": self.group(objects) if self.group and not q and show != "deleted" else None,
            "q": q, "show": show, "tabs": tabs, "is_deleted_tab": show == "deleted",
            "can_edit": _can(request, self.edit_cap), "total": tabs[0]["count"],
            "url_add": reverse(f"business:{self.name}_add"), "url_list": reverse(f"business:{self.name}"),
        })

    def form_view(self, request, pk=None):
        b = request.business
        obj = get_object_or_404(self._qs(b), pk=pk) if pk else None
        initial = self.initial(request) if (self.initial and not obj) else None
        form = self.form_class(request.POST or None, request.FILES or None, instance=obj, business=b, initial=initial)
        formset = None
        if self.formset_class:
            formset = self.formset_class(request.POST or None, instance=obj or self.model(business=b), prefix="rows",
                                         form_kwargs={"business": b})
        if request.method == "POST" and form.is_valid() and (formset is None or formset.is_valid()):
            with transaction.atomic():
                item = form.save(commit=False)
                item.business = b
                item.save()
                form.save_m2m()
                if formset is not None:
                    formset.instance = item
                    for row in formset.save(commit=False):
                        row.business = b
                        row.save()
                    for row in formset.deleted_objects:
                        row.delete()
                if self.after_save:
                    self.after_save(item, request)
            messages.success(request, _("Saved: %(name)s.") % {"name": item})
            nxt = request.GET.get("next")
            if nxt and url_has_allowed_host_and_scheme(nxt, {request.get_host()}):
                return redirect(nxt)
            return redirect(f"business:{self.name}")
        ctx = {"m": self, "form": form, "formset": formset, "obj": obj, "url_list": reverse(f"business:{self.name}")}
        if self.form_context:
            ctx.update(self.form_context(request))
        return render(request, self.form_template, ctx)

    def delete_view(self, request, pk):
        obj = get_object_or_404(self.model, pk=pk, business=request.business)
        problem = self.delete_check(obj) if self.delete_check else None
        if problem:
            messages.error(request, problem)
        else:
            obj.soft_delete()
            messages.success(request, _("“%(name)s” moved to Deleted. You can restore it any time.") % {"name": obj})
        return redirect(f"business:{self.name}")

    def restore_view(self, request, pk):
        obj = get_object_or_404(self.model.all_objects, pk=pk, business=request.business, is_deleted=True)
        name = getattr(obj, "name", None)
        if name and self.model.objects.filter(business=request.business, name__iexact=name).exists():
            messages.error(request, _("Another one is already called “%(name)s”. Rename it first.") % {"name": name})
            return redirect(reverse(f"business:{self.name}") + "?show=deleted")
        obj.restore()
        messages.success(request, _("“%(name)s” restored.") % {"name": obj})
        return redirect(f"business:{self.name}")


def _can(request, cap):
    from .access import can

    return cap is None or can(request.membership, cap)


# ── "+ Add new" popups ──────────────────────────────────────────────────────

@dataclass
class QuickAdd:
    form_path: str     # "apps.business.markets.forms.MarketQuickForm"
    capability: str
    title: str
    noun: str

    @property
    def form_class(self):
        from importlib import import_module

        module, name = self.form_path.rsplit(".", 1)
        return getattr(import_module(module), name)


QUICK_ADD = {}


def register_quick_add(kind, spec):
    QUICK_ADD[kind] = spec


def quick_add_context(kind, business):
    spec = QUICK_ADD[kind]
    return {"url": reverse("business:quick_add", args=[kind]), "title": spec.title, "noun": spec.noun,
            "form": spec.form_class(prefix=f"qa_{kind}", business=business)}


@business_access_required
@require_POST
def quick_add_view(request, kind):
    from .access import can

    spec = QUICK_ADD.get(kind)
    if spec is None:
        raise Http404
    if not can(request.membership, spec.capability):
        return JsonResponse({"ok": False, "errors": {"__all__": [_("You don't have permission to add this.")]}}, status=403)
    form = spec.form_class(request.POST, prefix=f"qa_{kind}", business=request.business)
    if not form.is_valid():
        errors = {k: [str(e) for e in v] for k, v in form.errors.items()}
        existing = None
        name = request.POST.get(f"qa_{kind}-name", "").strip()
        if name:
            existing = form._meta.model.objects.filter(business=request.business, name__iexact=name).first()
        if existing is not None and list(errors) == ["name"]:
            # Already there: just pick it instead of complaining.
            return JsonResponse({"ok": True, "id": existing.pk, "name": str(existing),
                                 "message": _("'%(name)s' already exists, so it's been selected.") % {"name": existing}})
        return JsonResponse({"ok": False, "errors": errors}, status=400)
    with transaction.atomic():
        obj = form.save(commit=False)
        obj.business = request.business
        obj.save()
        form.save_m2m()
    return JsonResponse({"ok": True, "id": obj.pk, "name": str(obj), "message": _("'%(name)s' added and selected.") % {"name": obj}}, status=201)
