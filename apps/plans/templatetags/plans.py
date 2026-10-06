from django import template

register = template.Library()


@register.simple_tag
def plan_status(party):
    """The installment plan's status for a creditor, debtor or shop, or None."""
    plan = getattr(party, "plan", None)
    if plan is None:
        return None
    from apps.plans.services import status

    return status(plan)
