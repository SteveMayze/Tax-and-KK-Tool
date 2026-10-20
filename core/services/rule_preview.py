"""Preview of the statement rules over a folder of joint-account statements (Phase 25, ADR 0025).

Per active rule: how many credit lines it matches and in which statements (by their printed number and year). Then the
number of lines matched by more than one rule, and of those how many disagree (a conflict: different kinds or tenants,
which the reader will not stage). Nothing printed contains an amount, a name, a pattern or a rule label: rules are shown
by their id and kind. The database is only read; nothing is changed.
"""
from pathlib import Path

from . import pdf_text, rvb_joint, statement_rules
from .dividend_statements import UnsupportedStatement


def preview(folder, recursive=False, rules=None):
    rules = statement_rules.load_rules() if rules is None else rules
    files = sorted(Path(folder).rglob('*.pdf') if recursive else Path(folder).glob('*.pdf'))
    per_rule = {r.id: [] for r in rules}
    result = {'files': len(files), 'joint': 0, 'other': 0, 'refused': 0, 'credits': 0, 'multi': 0, 'conflicts': 0, 'rules': rules,
              'per_rule': per_rule}
    for path in files:
        try:
            pages = pdf_text.extract_pages(path.read_bytes(), layout=True)
        except pdf_text.PdfError:
            result['refused'] += 1
            continue
        if not rvb_joint.recognises(pages):
            result['other'] += 1
            continue
        try:
            statement = rvb_joint.read_statement(pages)
        except UnsupportedStatement:
            result['refused'] += 1
            continue
        result['joint'] += 1
        label = f'{statement.number}/{statement.year}'
        for b in statement.bookings:
            if not b.is_credit:
                continue
            result['credits'] += 1
            found = statement_rules.matching_rules(rules, b.booking_date, b.counterparty, b.purpose)
            for r in found:
                per_rule[r.id].append(label)
            if len(found) > 1:
                result['multi'] += 1
                if len({r.kind for r in found}) > 1 or len({r.organisation for r in found}) > 1:
                    result['conflicts'] += 1
    return result


def render(result):
    out = [f'Files: {result["files"]} ({result["joint"]} joint-account statements, {result["other"]} other, {result["refused"]} not readable)',
           f'Credit lines read: {result["credits"]}']
    if not result['rules']:
        out.append('No active rules.')
    for r in result['rules']:
        labels = result['per_rule'][r.id]
        statements = sorted(set(labels))
        out.append(f'Rule #{r.id} ({r.kind}): {len(labels)} lines in {len(statements)} statements'
                   + (f' ({", ".join(statements)})' if statements else ''))
    out.append(f'Lines matched by more than one rule: {result["multi"]}, of which conflicts (not staged): {result["conflicts"]}')
    return '\n'.join(out)
