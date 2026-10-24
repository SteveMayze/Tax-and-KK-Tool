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


# Broker income (Phase 32, ADR 0033): the broker is part of the organisation, and money-market fund income is recorded as
# Interest (a recording choice only; how tax and SBK treat it stays open). Only the two broker readers use these.
ETRADE, FIDELITY = 'E*Trade', 'Fidelity'
FIDELITY_ABBREVIATION = 'FID'
FUND_INCOME_CATEGORY, STOCK_DIVIDEND_CATEGORY = 'Interest', 'Dividends'


def broker_organisation(broker: str, security_name: str) -> str:
    """`broker` + the tidied security name, single spaces. A leading broker name (any case) is not doubled and takes the
    owner's spelling; Fidelity's printed abbreviation `FID` (a whole first word) is replaced by the broker name."""
    words = security_name.split()
    first = words[0].casefold() if words else ''
    if first == broker.casefold() or (broker == FIDELITY and first == FIDELITY_ABBREVIATION.casefold()):
        words = words[1:]
    return ' '.join([broker, *words])


def broker_category(is_fund: bool) -> str:
    return FUND_INCOME_CATEGORY if is_fund else STOCK_DIVIDEND_CATEGORY
