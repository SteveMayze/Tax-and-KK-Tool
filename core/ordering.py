"""Explicit, engine-independent text ordering (ADR 0035).

SQLite sorts text by its bytes; PostgreSQL sorts by the database's locale (`en_US.utf8`: case and accents mostly
ignored). Every list of names a page, report, CSV, PDF or ZIP shows is therefore sorted HERE, in Python, never by
`order_by('name')`. The owner chose (2026-11-27) to keep the order SQLite gave before the move: plain Unicode
code-point order of the text as stored. For UTF-8 that is exactly SQLite's byte order (BINARY collation), so nothing
the owner sees changes: upper-case letters sort before lower-case ones, and "Ä" after "Z". Ties are broken by the
primary key, so the order is fully determined. `Meta.ordering` stays (no migration) but nothing displayed relies on it.
"""


def text_key(value):
    """Sort key for one text: the text itself (code-point order, the same as SQLite's byte order for UTF-8)."""
    return '' if value is None else str(value)


def by_text(objects, attr='name'):
    """Model instances sorted by one text attribute, ties by primary key. Returns a list."""
    return sorted(objects, key=lambda o: (text_key(getattr(o, attr)), o.pk))


def payments_by_date_and_organisation(payments):
    """Payment date, then organisation name, then id (the order of the payments page and the tax summary)."""
    return sorted(payments, key=lambda p: (p.payment_date, text_key(p.organisation.name), p.pk))
