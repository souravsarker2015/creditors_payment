"""Categories for creditors and debtors: a list each person keeps.

Everyone starts with the familiar ones (Family, Friend, Bank, … Other) and can
add their own with the + beside the dropdown, or rename, hide and delete them on
the Categories page. Each starter remembers the code it began as (FAMILY, …), so
links, CSV files and backups made before the list became editable still find it.

Shared by apps.creditors and apps.debtors; each has its own table (a subclass of
PersonCategory) and its own starter list (a TextChoices).
"""
from django.conf import settings
from django.contrib import messages
from django.db import models
from django.db.models import Count
from django.shortcuts import redirect, render
from django.utils.html import format_html
from django.utils.translation import gettext as _, gettext_lazy, override


class PersonCategory(models.Model):
    """One category in a person's list. A subclass sets STARTERS to its TextChoices."""

    STARTERS = None

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="%(app_label)s_categories")
    name = models.CharField(gettext_lazy("Name"), max_length=80)
    # The starter it began as ("FAMILY"…), empty for one the person added.
    code = models.CharField(max_length=32, blank=True, default="", editable=False)
    is_active = models.BooleanField(gettext_lazy("In use"), default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True
        ordering = ["name"]

    def __str__(self):
        return self.label

    @property
    def label(self):
        """A starter that still has its first name shows in the reader's language; a renamed or added one as typed."""
        starter = self.starter
        if starter is not None and self.name == english(starter.label):
            return str(starter.label)
        return self.name

    @property
    def starter(self):
        if self.code and self.STARTERS is not None and self.code in self.STARTERS.values:
            return self.STARTERS(self.code)
        return None


def english(label):
    with override("en"):
        return str(label)


def ensure_starters(model, user, people):
    """The starter list, the first time someone opens their creditors (or debtors).
    Nothing is added for anyone who already has a category or a person — so a list
    someone has trimmed down stays as they left it."""
    if user is None or not user.is_authenticated:
        return
    mine = model.objects.filter(user=user)
    if mine.exists() or people.exists():
        return
    model.objects.bulk_create([model(user=user, name=english(c.label), code=c.value) for c in model.STARTERS],
                              ignore_conflicts=True)


def starting_category(model, user, people):
    """The category a new person gets when none is picked: "Other" (the starter list is made first if there's none)."""
    ensure_starters(model, user, people)
    return default_category(model, user)


def default_category(model, user):
    """"Other", where a new person starts unless they pick something else."""
    return model.objects.filter(user=user, code="OTHER", is_active=True).first()


def choices(model, user):
    """[(id as text, name)] for the include/exclude filter — hidden ones too, as people may still be in them."""
    return sorted(((str(c.pk), c.label) for c in model.objects.filter(user=user)), key=lambda c: c[1].lower())


def selected(request, model, user):
    """The categories picked in the filter, as ids (text). A link from before the
    list was editable (?category=FAMILY) still works: the code finds the starter."""
    mine = model.objects.filter(user=user)
    ids = {str(pk) for pk in mine.values_list("pk", flat=True)}
    by_code = {code: str(pk) for pk, code in mine.exclude(code="").values_list("pk", "code")}
    out = []
    for value in request.GET.getlist("category"):
        value = (value or "").strip()
        pk = value if value in ids else by_code.get(value.upper())
        if pk and pk not in out:
            out.append(pk)
    return out


def find(model, user, text):
    """The category a CSV cell names — by name, by its name in the reader's
    language, or by its old code (FRIEND) — else a new one with that name.
    An empty cell is "Other", as before."""
    text = " ".join((text or "").split())[:80]
    mine = list(model.objects.filter(user=user))
    if not text:
        return next((c for c in mine if c.code == "OTHER"), None)
    low = text.lower()
    for c in mine:
        if low == c.code.lower() or low in names_of(c):
            return c
    return model.objects.create(user=user, name=text)


def names_of(category):
    """Every name a category goes by: its own, and for an untouched starter its name in each of the app's languages."""
    out = {category.name.lower(), category.label.lower()}
    starter = category.starter
    if starter is not None and category.name == english(starter.label):
        for code, _name in settings.LANGUAGES:
            with override(code):
                out.add(str(starter.label).lower())
    return out


def same_name(model, user, name, exclude_pk=None):
    """The category already called this (in any of the app's languages), if any."""
    low = name.lower()
    for c in model.objects.filter(user=user).exclude(pk=exclude_pk):
        if low in names_of(c):
            return c
    return None


def field_help(manage_url):
    return format_html('{} <a href="{}" class="link">{}</a>',
                       _("Missing one? Use + to add it."), manage_url, _("Change the list"))


def setup_field(form, model, user, people, manage_url, quick_add):
    """The Category dropdown on the creditor/debtor form: this person's list (and
    the one already chosen, even if hidden since), + to add one, "Other" to start."""
    field = form.fields.get("category")
    if field is None:
        return
    if user is None or not user.is_authenticated:
        del form.fields["category"]      # no one signed in (a script, a test): left out, as the wallet is; saving puts them in "Other"
        return
    ensure_starters(model, user, people)
    key = form.add_prefix("category")
    posted = form.data.get(key) if form.is_bound else None
    if posted and not str(posted).isdigit():
        # An old code ("FRIEND") from a page opened before the update, or a form saved offline and sent later.
        match = model.objects.filter(user=user, code=str(posted).strip().upper()).first()
        if match is not None:
            form.data = form.data.copy()
            form.data[key] = str(match.pk)
    current = form.instance.category_id
    field.queryset = model.objects.filter(user=user).filter(models.Q(is_active=True) | models.Q(pk=current))
    # in the order of the names shown (a starter's name is translated, so the database's order isn't it)
    field.choices = [(c.pk, c.label) for c in sorted(field.queryset, key=lambda c: c.label.lower())]
    field.required = True            # as before: everyone is in a category ("Other" to start with)
    field.empty_label = None
    field.quick_add = quick_add
    field.help_text = field_help(manage_url)
    if not form.instance.pk and not form.is_bound and "category" not in form.initial:
        start = default_category(model, user)
        if start:
            form.initial["category"] = start.pk


class NameForm:
    """The quick-add popup's form for a category: just the name. Typing a starter's
    name in the reader's language ("পরিবার") finds that starter instead of making a twin."""

    allow_same_name = True

    def clean_name(self):
        name = " ".join((self.cleaned_data.get("name") or "").split())
        from apps.business.core.audit import current_user

        user = current_user()
        if name and user is not None and user.is_authenticated:
            match = same_name(self._meta.model, user, name)
            if match is not None:
                return match.name
        return name


def manage(request, *, model, people_name, title, subtitle, back_url, back_label, list_url, kind):
    """The Categories page: add, rename, hide (and show again) or delete. One in use can't
    be deleted — hide it, or move those people to another category first."""
    user = request.user
    people = getattr(user, people_name)
    ensure_starters(model, user, people.all())
    mine = model.objects.filter(user=user)
    if request.method == "POST":
        action, name = request.POST.get("action"), " ".join((request.POST.get("name") or "").split())[:80]
        pk = request.POST.get("pk", "")
        obj = mine.filter(pk=pk).first() if pk.isdigit() else None
        if action == "add" and name:
            twin = same_name(model, user, name)
            if twin:
                messages.info(request, _("“%(name)s” is already in the list.") % {"name": twin.label})
            else:
                model.objects.create(user=user, name=name)
                messages.success(request, _("Added %(name)s.") % {"name": name})
        elif action == "rename" and obj and name and name != obj.label:   # (saved unchanged: a starter keeps following the language)
            twin = same_name(model, user, name, exclude_pk=obj.pk)
            if twin:
                messages.error(request, _("“%(name)s” is already in the list.") % {"name": twin.label})
            else:
                obj.name = name
                obj.save(update_fields=["name"])
                messages.success(request, _("Renamed to %(name)s. Everyone in it shows the new name.") % {"name": name})
        elif action == "toggle" and obj:
            obj.is_active = not obj.is_active
            obj.save(update_fields=["is_active"])
            if obj.is_active:
                messages.success(request, _("%(name)s is offered again.") % {"name": obj.label})
            else:
                messages.success(request, _("%(name)s is hidden from the list. People already in it keep it.") % {"name": obj.label})
        elif action == "delete" and obj:
            if people.filter(category=obj).exists():
                messages.error(request, _("%(name)s is still used — hide it instead, or move those people to another category first.") % {"name": obj.label})
            else:
                obj.delete()
                messages.success(request, _("Deleted %(name)s.") % {"name": obj.label})
        return redirect(request.path)
    rows = sorted(mine.annotate(n=Count(people.model._meta.get_field("category").remote_field.related_name)),
                  key=lambda c: (not c.is_active, c.label.lower()))
    return render(request, "core/people_categories.html", {
        "rows": rows, "title": title, "subtitle": subtitle, "back_url": back_url, "back_label": back_label,
        "list_url": list_url, "kind": kind,
    })
