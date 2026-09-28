from django.utils.translation import gettext_lazy as _

from apps.business.core.crud import Master

from .forms import SpeciesForm
from .models import Species

species = Master(
    name="species", model=Species, form_class=SpeciesForm,
    title=_("Fish species"), subtitle=_("The fish you raise and sell. Names show in Bangla when the app is in Bangla."),
    add_label=_("Add species"), row_template="business/species/row.html",
    search_fields=("name", "name_bn", "scientific_name"), select_related=("default_unit",), icon="fish",
    empty_title=_("No fish species yet"), empty_text=_("Add the fish you raise — Rui, Katla, Pangas, Tilapia…"),
    note=(_("About fish species"),
          _("Add every fish you raise or sell. They're used when you release fingerlings, weigh, harvest and sell."),
          _("Give each one a Bangla name; it's shown instead of the English one when the app is in Bangla."),
          _("The default unit (kg, mon or pieces) is picked first when you sell that fish.")),
)
