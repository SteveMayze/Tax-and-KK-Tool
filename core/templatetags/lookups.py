from django import template

from core.models import IncomeCategory, Organisation

register = template.Library()


@register.simple_tag
def active_names(kind):
    model = Organisation if kind == 'organisation' else IncomeCategory
    return list(model.objects.filter(active=True).values_list('name', flat=True))
