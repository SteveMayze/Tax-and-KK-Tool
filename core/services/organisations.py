"""Organisation strings for imported payments (Phase 15, ADR 0015). The payer is the organisation.

Banks have fixed names kept in BANK_ORGANISATIONS (the reader ids of the bank readers are added with those readers).
Securities (company stock, money-market funds) are named as the statement prints them, tidied by the one function below
so that every reader gives the identical string for the same security. No security names are kept in the code."""
import re

BANK_ORGANISATIONS = {
    'hsbc_savings': 'HSBC UK (Flexible Saver)',
    'rvb_giro': 'RVB (Girokonto)',
    'mecu_account': 'MECU',
    'ordminnett_cmt': 'Ord Minnett',
}

SMALL_WORDS = {'LTD': 'Ltd', 'PTY': 'Pty', 'AND': 'and', 'OF': 'of', 'THE': 'the', 'CO': 'Co', 'INC': 'Inc', 'PLC': 'Plc',
               'CORP': 'Corp'}


def tidy_security_name(name: str) -> str:
    """A printed security or issuer name as an organisation string: reference prefix and trailing separators removed,
    and an all-capitals name written in capitals-and-lowercase ("ENDEAVOUR GROUP LIMITED" -> "Endeavour Group Limited")."""
    name = re.sub(r'^\S*_V\d+', '', name)                       # a reference printed in front of the name
    name = re.sub(r'[|,;:]+$', '', name.strip('| ')).strip()
    if name.isupper():
        name = ' '.join(SMALL_WORDS.get(w, w if len(w) <= 3 or re.search(r'\d', w) else w.capitalize()) for w in name.split())
    return name
