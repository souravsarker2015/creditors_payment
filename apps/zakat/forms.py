from django import forms

from .models import ZakatSettings

NUM = {"class": "form-input", "inputmode": "decimal", "step": "any", "min": "0"}


class ZakatForm(forms.ModelForm):
    class Meta:
        model = ZakatSettings
        fields = ["basis", "gold_price", "silver_price", "gold_grams", "silver_grams", "other_assets", "other_debts", "farm_share"]
        widgets = {
            "basis": forms.RadioSelect,
            **{f: forms.NumberInput(attrs={**NUM, "x-model.number": f}) for f in
               ("gold_price", "silver_price", "gold_grams", "silver_grams", "other_assets", "other_debts", "farm_share")},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["basis"].widget.attrs["x-model"] = "basis"
        for name, f in self.fields.items():
            if name != "basis":
                f.required = False          # empty means 0
            if name != "basis" and self.instance.pk:
                value = getattr(self.instance, name)
                self.initial[name] = format(value.normalize(), "f") if hasattr(value, "normalize") else value

    def clean(self):
        data = super().clean()
        for name in self.fields:
            if name != "basis" and data.get(name) in (None, ""):
                data[name] = 100 if name == "farm_share" else 0
        return data
