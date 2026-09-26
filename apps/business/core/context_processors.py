from .access import BUSINESS, active_membership, can, request_dashboards


def dashboards(request):
    """Dashboard switcher data for the topbar, and the active business for
    business pages."""
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {}
    active = BUSINESS if request.path.startswith("/business/") else "personal"
    ctx = {"available_dashboards": request_dashboards(request), "active_dashboard": active}
    if active == BUSINESS:
        m = getattr(request, "membership", None) or active_membership(request)
        ctx["membership"] = m
        ctx["business"] = m.business if m else None
        ctx["biz_can"] = {cap: can(m, cap) for cap in ("enter_data", "delete", "view_reports", "view_finance", "manage_settings", "manage_team")}
    return ctx
