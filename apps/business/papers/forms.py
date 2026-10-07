from django import forms
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from apps.business.core.crud import BusinessForm
from apps.core.receipts import ReceiptInput

from .models import FarmPaper


class FarmPaperForm(BusinessForm):
    unique_name = ()
    tips = {
        "expires_on": _("The farm's to-do list reminds you before this date, so there's time to renew."),
        "remind_days": _("How early to start reminding you. Renewals that need an office visit may need 30–60 days."),
        "file": _("A photo of the paper (or a PDF). Only owners and managers of this farm can open it."),
    }
    layout = [("title",), ("kind", "pond"), ("number", "issued_by"), ("issued_on", "expires_on"), ("remind_days",), ("file",), ("notes",)]

    class Meta:
        model = FarmPaper
        fields = ["title", "kind", "pond", "number", "issued_by", "issued_on", "expires_on", "remind_days", "file", "notes"]
        widgets = {"issued_on": forms.DateInput(), "expires_on": forms.DateInput(), "file": ReceiptInput()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["pond"].empty_label = _("The whole farm")
        self.fields["file"].widget.attrs.pop("class", None)
        if self.instance.pk and self.instance.file:
            self.fields["file"].widget.view_url = reverse("business:paper_file", args=[self.instance.pk])
            self.fields["file"].widget.view_label = _("See the paper")

    def clean(self):
        data = super().clean()
        if data.get("issued_on") and data.get("expires_on") and data["expires_on"] < data["issued_on"]:
            self.add_error("expires_on", _("This is before the day it was issued."))
        return data
