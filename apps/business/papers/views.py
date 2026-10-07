import mimetypes
import os
from datetime import date

from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext_lazy as _

from apps.business.core.crud import Master
from apps.business.core.decorators import business_access_required

from .forms import FarmPaperForm
from .models import FarmPaper

CAP = "manage_settings"


def _by_state(objects):
    """Expired first, then those to renew soon, then the rest."""
    order = (("expired", _("Expired")), ("soon", _("Renew soon")), ("valid", _("Valid")), ("forever", _("No end date")))
    groups = [(label, [o for o in objects if o.state == key]) for key, label in order]
    groups = [g for g in groups if g[1]]
    return groups if len(groups) > 1 else []


papers = Master(
    name="papers", model=FarmPaper, form_class=FarmPaperForm,
    title=_("Farm papers"), subtitle=_("Licences, registrations, lease and land papers: a copy of each, and a reminder before it runs out."),
    add_label=_("Add a paper"), row_template="business/papers/row.html", icon="note",
    view_cap=CAP, edit_cap=CAP, search_fields=("title", "number", "issued_by", "notes"), select_related=("pond",), group=_by_state,
    empty_title=_("Keep the farm's papers safe here"),
    empty_text=_("Add the trade licence, fish farm registration, lease agreements and land papers with a photo of each. You'll be reminded before any of them runs out."),
    note=(_("How farm papers work"),
          _("Take a photo of each paper and add it with its number and the day it runs out."),
          _("The farm's to-do list warns you before a paper expires, so there's time to renew it."),
          _("Only the owner and managers can see these papers.")),
)


@business_access_required(capability=CAP)
def paper_file_view(request, pk):
    paper = get_object_or_404(FarmPaper.all_objects, pk=pk, business=request.business)
    if not paper.file:
        raise Http404
    try:
        handle = paper.file.open("rb")
    except (FileNotFoundError, OSError):
        raise Http404
    response = FileResponse(handle, content_type=mimetypes.guess_type(paper.file.name)[0] or "application/octet-stream")
    response["Content-Disposition"] = f'inline; filename="{os.path.basename(paper.file.name)}"'
    response["Cache-Control"] = "private, max-age=3600"
    response["X-Content-Type-Options"] = "nosniff"
    return response


def due_papers(business, today=None):
    """Papers expired or inside their reminder window, soonest first."""
    today = today or date.today()
    return [p for p in FarmPaper.objects.filter(business=business, expires_on__isnull=False).select_related("pond")
            if p.state in ("expired", "soon")]
