from django import template

from core.services.pdf_text import mask_digit_runs

register = template.Library()


@register.filter
def masked(value):
    """File names are shown with digit runs of six or more hidden (account and reference numbers)."""
    return mask_digit_runs(str(value))
