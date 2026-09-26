from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from apps.business.core.crud import Master

from .forms import FeedProductForm
from .models import FeedForm, FeedProduct

feed_products = Master(
    name="feed_products", model=FeedProduct, form_class=FeedProductForm,
    title=_("Feed products"), subtitle=_("The feeds you buy: bag size, usual price and who sells them. Stock and usage come next."),
    add_label=_("Add feed"), row_template="business/feed/row.html", icon="banknotes",
    search_fields=("name", "brand"), select_related=("bag_unit",), prefetch=("suppliers",),
    filters=[(k, label, Q(form=k)) for k, label in FeedForm.choices[:2]],
    empty_title=_("No feed products yet"), empty_text=_("Add the feeds you use — brand, bag size and price — so purchases and daily feeding are quick to enter."),
)
