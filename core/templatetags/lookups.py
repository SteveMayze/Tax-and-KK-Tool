from django import template

from core.models import IncomeCategory, Organisation
from core.ordering import text_key

register = template.Library()


@register.simple_tag
def active_names(kind):
    model = Organisation if kind == 'organisation' else IncomeCategory
    return sorted(model.objects.filter(active=True).values_list('name', flat=True), key=text_key)   # ADR 0035
