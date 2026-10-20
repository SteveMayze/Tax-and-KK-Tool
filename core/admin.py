from django.contrib import admin

from .models import StatementRule


@admin.register(StatementRule)
class StatementRuleAdmin(admin.ModelAdmin):
    """Where the owner defines what counts as rent on the joint account (Phase 25). Needs DJANGO_ENABLE_ADMIN=1."""
    list_display = ('label', 'kind', 'match_on', 'organisation', 'valid_from', 'valid_to', 'active')
    list_filter = ('kind', 'active')
