from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from core.icons import ICONS

register = template.Library()


@register.simple_tag
def icon(name):
    """One decorative inline SVG (Phase 29, ADR 0030). The control around it carries the accessible name."""
    return format_html(
        '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">{}</svg>', mark_safe(ICONS[name]))
