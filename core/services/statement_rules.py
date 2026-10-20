"""Matching rules for bank-statement lines (Phase 25, ADR 0025): normalisation, pattern compiling and rule matching.

The rules are data (the model StatementRule, edited by the owner), never code: no name appears in this module.
Pure functions only; nothing here touches the database except `load_rules`, which reads active rules.

Text is compared in two normal forms, so one spelling of a name matches the others:
  expanded  case-folded, ä/ö/ü/ß written ae/oe/ue/ss, other diacritics removed  ("Jürgen Köhler" -> "juergen koehler")
  stripped  case-folded, umlauts reduced to the bare letter                        ("Jürgen Köhler" -> "jurgen kohler")
In both, hyphens become spaces and runs of whitespace collapse. A pattern is folded the same way (letters only, its case
and regular-expression syntax are left alone) and is searched case-insensitively; it matches when the expanded pattern
finds the expanded text or the stripped pattern finds the stripped text.
"""
import datetime
import re
import unicodedata
from dataclasses import dataclass

from django.utils.translation import gettext

EXPAND = {'ä': 'ae', 'ö': 'oe', 'ü': 'ue', 'ß': 'ss', 'Ä': 'Ae', 'Ö': 'Oe', 'Ü': 'Ue', 'ẞ': 'Ss'}
STRIP = {'ä': 'a', 'ö': 'o', 'ü': 'u', 'ß': 'ss', 'Ä': 'A', 'Ö': 'O', 'Ü': 'U', 'ẞ': 'Ss'}

KIND_TENANT_RENT = 'tenant_rent'
KIND_SERVICE_CHARGE = 'service_charge_settlement'
KINDS = (KIND_TENANT_RENT, KIND_SERVICE_CHARGE)
MATCH_ON = ('counterparty', 'purpose', 'either')


class RuleError(ValueError):
    """A rule pattern that cannot be used (message is safe to show)."""


class RuleConflict(Exception):
    """One booking matched rules that disagree (different kinds, or the same kind for different organisations)."""


def _fold(text, table):
    out = ''.join(table.get(c, c) for c in text)
    decomposed = unicodedata.normalize('NFKD', out)
    return ''.join(c for c in decomposed if not unicodedata.combining(c))


def normalise(text, stripped=False):
    """The comparison form of a line of statement text (see the module docstring)."""
    folded = _fold(text, STRIP if stripped else EXPAND).casefold()
    return re.sub(r'\s+', ' ', folded.replace('-', ' ')).strip()


def compile_pattern(pattern):
    """-> (expanded regex, stripped regex). Raises RuleError for an empty, invalid or empty-matching pattern."""
    if not pattern or not pattern.strip():
        raise RuleError(gettext('The pattern is empty.'))
    compiled = []
    for table in (EXPAND, STRIP):
        try:
            rx = re.compile(_fold(pattern.strip(), table), re.IGNORECASE)
        except re.error as e:
            raise RuleError(gettext('The pattern is not a valid regular expression: %(why)s') % {'why': e.msg})
        if rx.search(''):
            raise RuleError(gettext('The pattern matches the empty text, so it would match every line. Make it more specific.'))
        compiled.append(rx)
    return tuple(compiled)


def pattern_matches(compiled, text):
    expanded, stripped = compiled
    return bool(expanded.search(normalise(text)) or stripped.search(normalise(text, stripped=True)))


@dataclass(frozen=True)
class Rule:
    id: int
    label: str
    kind: str
    pattern: object                 # compiled (expanded, stripped)
    match_on: str
    organisation: str
    valid_from: datetime.date | None
    valid_to: datetime.date | None

    def in_force(self, date):
        return (self.valid_from is None or date >= self.valid_from) and (self.valid_to is None or date <= self.valid_to)

    def matches(self, counterparty, purpose):
        if self.match_on == 'counterparty':
            return pattern_matches(self.pattern, counterparty)
        if self.match_on == 'purpose':
            return pattern_matches(self.pattern, purpose)
        return pattern_matches(self.pattern, counterparty) or pattern_matches(self.pattern, purpose)


def load_rules():
    """Active rules from the database, patterns compiled. The model validates a pattern on save, so a stored pattern
    that no longer compiles (edited outside the app) raises RuleError here instead of being skipped."""
    from core.models import StatementRule
    return [Rule(r.pk, r.label, r.kind, compile_pattern(r.pattern), r.match_on, r.organisation.strip(), r.valid_from, r.valid_to)
            for r in StatementRule.objects.filter(active=True).order_by('pk')]


def matching_rules(rules, date, counterparty, purpose):
    """Every rule in force on `date` that matches the credit's counterparty line and/or purpose."""
    return [r for r in rules if r.in_force(date) and r.matches(counterparty, purpose)]


def match_credit(rules, date, counterparty, purpose):
    """The single rule a credit matches, or None. Raises RuleConflict when the matched rules disagree: a booking must
    never be both rent and a service-charge settlement, or rent of two tenants (refuse rather than guess)."""
    found = matching_rules(rules, date, counterparty, purpose)
    if not found:
        return None
    if len({r.kind for r in found}) > 1 or len({r.organisation for r in found}) > 1:
        raise RuleConflict()
    return found[0]
