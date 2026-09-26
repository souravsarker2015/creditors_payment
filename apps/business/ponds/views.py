from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from apps.business.core.crud import Master

from .forms import PondForm
from .models import Pond, PondStatus

ponds = Master(
    name="ponds", model=Pond, form_class=PondForm,
    title=_("Ponds"), subtitle=_("Every pond or gher you farm — its size, whether it's leased, and what's in it now."),
    add_label=_("Add pond"), row_template="business/ponds/card.html", cards=True, icon="fish",
    search_fields=("name", "code", "location", "lease_from"), select_related=("area_unit",),
    filters=[("in_use", _("Fish in it"), Q(status=PondStatus.IN_USE)),
             ("leased", _("Leased"), Q(ownership="leased"))],
    empty_title=_("Add your first pond"), empty_text=_("Give it a name and size. Stocking, feeding and harvests will be recorded per pond, so you'll see what each one earns."),
)
