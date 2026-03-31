from django import template
from django.db.models import Sum

register = template.Library()

@register.filter
def sum_amount(queryset):
    return queryset.aggregate(total=Sum('amount'))['total'] or 0
