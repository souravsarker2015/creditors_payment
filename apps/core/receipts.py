"""Receipt photos: where they're stored, how big they may be, and a private
viewer — a receipt is only ever served to the person it belongs to (or, for
the farm, to team members who may see money), never as a public media URL."""
import mimetypes
import os
import uuid

from django import forms
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

MAX_MB = 8
EXTENSIONS = ["jpg", "jpeg", "png", "webp", "heic", "pdf"]


def personal_receipt_path(instance, filename):
    ext = os.path.splitext(filename)[1].lower()[:6] or ".jpg"
    return f"receipts/{instance.user_id}/{uuid.uuid4().hex}{ext}"


def max_size(f):
    if f and getattr(f, "size", 0) > MAX_MB * 1024 * 1024:
        raise ValidationError(_("The photo is too big (over %(mb)s MB). Try a smaller one.") % {"mb": MAX_MB})


RECEIPT_VALIDATORS = [FileExtensionValidator(EXTENSIONS), max_size]


class ReceiptInput(forms.ClearableFileInput):
    """Photo picker that shrinks big phone photos before upload and links the
    current receipt through the private viewer instead of its file path."""

    template_name = "partials/receipt_input.html"

    def __init__(self, attrs=None):
        super().__init__({"accept": "image/*,application/pdf", "data-shrink": "1600", **(attrs or {})})
        self.view_url = ""

    def get_context(self, name, value, attrs):
        ctx = super().get_context(name, value, attrs)
        ctx["widget"]["view_url"] = self.view_url
        return ctx


def attach_viewer(form, kind):
    """Point the receipt widget at the private viewer for an existing receipt."""
    field = form.fields.get("receipt")
    if field is not None and form.instance.pk and getattr(form.instance, "receipt", None):
        field.widget.view_url = reverse("receipt_view", args=[kind, form.instance.pk])


def _record(request, kind, pk):
    if kind == "expense":
        from apps.expense.models import Expense

        return get_object_or_404(Expense, pk=pk, user=request.user)
    if kind == "bazar":
        from apps.household.models import Purchase

        return get_object_or_404(Purchase, pk=pk, user=request.user)
    if kind == "farm":
        from apps.business.core.access import active_membership, can
        from apps.business.finance.models import Transaction

        t = get_object_or_404(Transaction.objects.select_related("business"), pk=pk)
        m = active_membership(request)
        if m is None or m.business_id != t.business_id or not can(m, "view_finance"):
            raise Http404
        return t
    raise Http404


@login_required
def receipt_view(request, kind, pk):
    record = _record(request, kind, pk)
    f = getattr(record, "receipt", None)
    if not f:
        raise Http404
    try:
        handle = f.open("rb")
    except (FileNotFoundError, OSError):
        raise Http404
    content_type = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
    response = FileResponse(handle, content_type=content_type)
    response["Content-Disposition"] = f'inline; filename="{os.path.basename(f.name)}"'
    response["Cache-Control"] = "private, max-age=3600"
    response["X-Content-Type-Options"] = "nosniff"
    return response
