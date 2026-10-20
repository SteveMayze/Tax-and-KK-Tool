"""Synthetic PDFs for tests (Phase 14). Nothing here is real data: invented companies, holders and amounts.

make_pdf() writes a minimal text PDF by hand (no extra dependency), one text line per entry, so a test controls exactly
which lines the extractor sees. The STATEMENTS below imitate the *structure* of the registries' layouts (label order,
where values sit, which anchors exist); the expected results are worked out by hand next to each one."""
from decimal import Decimal as D
import datetime


def _escape(text):
    return text.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')


def make_pdf(pages):
    """pages: list of lists of text lines. A page with no lines is a blank page (no text layer)."""
    objects = []                       # object number n is objects[n - 1]
    objects.append(b'<< /Type /Catalog /Pages 2 0 R >>')
    kids = ' '.join(f'{4 + 2 * i} 0 R' for i in range(len(pages)))
    objects.append(f'<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>'.encode())
    objects.append(b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>')
    for i, lines in enumerate(pages):
        content_number = 5 + 2 * i
        objects.append(f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 3 0 R >> >> '
                       f'/Contents {content_number} 0 R >>'.encode())
        # A line is a string, or a list of (x, text) cells placed at their own x positions (a table row).
        stream = '\n'.join(
            ' '.join(f'BT /F1 9 Tf 1 0 0 1 {x} {800 - 13 * n} Tm ({_escape(text)}) Tj ET' for x, text in line)
            if isinstance(line, list) else f'BT /F1 9 Tf 1 0 0 1 30 {800 - 13 * n} Tm ({_escape(line)}) Tj ET'
            for n, line in enumerate(lines))
        data = stream.encode('cp1252', 'replace')
        objects.append(b'<< /Length ' + str(len(data)).encode() + b' >>\nstream\n' + data + b'\nendstream')
    out = bytearray(b'%PDF-1.4\n')
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f'{number} 0 obj\n'.encode() + body + b'\nendobj\n'
    xref = len(out)
    out += f'xref\n0 {len(objects) + 1}\n'.encode() + b'0000000000 65535 f \n'
    for offset in offsets:
        out += f'{offset:010d} 00000 n \n'.encode()
    out += f'trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode()
    return bytes(out)


# name -> (lines, expected (code, payment date, record date, gross, net, withholding, reinvested))
MUFG_STYLE = [
    'Payment Advice', 'DIVIDEND STATEMENT', 'Reference No.: X********0001', 'Payment Date: 12 May 2025',
    'ACME MINING LIMITED', 'ABN: 11 111 111 111', 'MR TEST HOLDER', '1 EXAMPLE STREET', 'Record Date: 14 April 2025',
    'Security Description Dividend Rate per Share Participating Shares Unfranked Amount Franked Amount Total Payment Franking Credit',
    'ACM - ORDINARY SHARES $0.10 500 $0.00 $50.00 $50.00 $21.43', 'Less Withholding Tax $0.00', 'Net Amount AUD 50.00',
    'Represented By:', 'Direct Credit amount AUD 50.00', 'BANKING INSTRUCTIONS The amount of AUD 50.00 was deposited to the bank account',
]
EXPECT_MUFG = ('ACM', datetime.date(2025, 5, 12), datetime.date(2025, 4, 14), D('50.00'), D('50.00'), D('0.00'), False)

COMPUTERSHARE_LABELS_FIRST = [
    'Zed Resources Limited', 'ABN 22 222 222 222', 'Your Shareholding', 'RECORD DATE PAYMENT DATE',
    'T 0000001 000 ZED', 'MR TEST HOLDER', 'Your Payment Instruction', 'Amount Deposited',
    'FY2025 Final Dividend Payment - Dividend Statement & Direct Credit Advice',
    'Amount per Security Number of Securities Franked Amount Unfranked Amount Gross Payment',
    'Ordinary Shares A$0.350000 120 A$42.00 A$0.00 A$42.00', 'Net Payment A$42.00', 'Australian Franking Credit A$18.00',
    '3 June 2025', '24 June 2025', 'A$42.00',
]
EXPECT_COMPUTERSHARE = ('ZED', datetime.date(2025, 6, 24), datetime.date(2025, 6, 3), D('42.00'), D('42.00'), D('0.00'), False)

LABEL_FIRST_NET = [
    'NOTIFICATION OF THE INTERIM DIVIDEND FOR THE HALF YEAR ENDED 31 DECEMBER 2024', 'This dividend is 100% unfranked.',
    'Quick Pharma Limited ABN 33 333 333 333',
    'BANKING INSTRUCTIONS', 'NET DIVIDEND PAYMENT', 'RATE NO. OF SHARES UNFRANKED AMOUNT FRANKED AMOUNT FRANKING CREDIT',
    'Payment Date 9 July 2025', 'Record Date 10 June 2025', 'T 0000002 000 QPH',
    'Ordinary Shares AU$1.500000 100 AU$150.00 AU$0.00 AU$0.00', 'AU$150.00',
]
EXPECT_LABEL_FIRST = ('QPH', datetime.date(2025, 7, 9), datetime.date(2025, 6, 10), D('150.00'), D('150.00'), D('0.00'), False)

VALUE_PER_LINE = [
    'Dividend Statement', 'Dividend advice - Final dividend for the year ended 31 December 2024',
    'Record Date', 'Shareholding', 'Payable Date', 'AUD Dividend Rate Per Share', 'AUD Franking Credits',
    'AUD Unfranked Dividend Payable', 'AUD Dividend Amount', 'AUD Franked Dividend Payable', 'AUD Tax Withheld',
    'T 0000003 000 RTO', '10 June 2025', '17 July 2025', '31 December 2024', 'Quoted', '370', '$3.337000',
    '$1,234.50', '$0.00', '$500.00', '$0.00', '$1,234.50', 'BANKING INSTRUCTION', 'Date Payable: 17 July 2025',
    'Payment Amount: AUD1,234.50', 'ABN 44 444 444 444',
]
EXPECT_VALUE_PER_LINE = ('RTO', datetime.date(2025, 7, 17), None, D('1234.50'), D('1234.50'), D('0.00'), False)

AMP_COLUMNS = [
    'Example Pensions Limited ABN 55 555 555 555', '2024 final dividend', 'DIVIDEND RATE ORDINARY SHARES HELD',
    'GROSS DIVIDEND AUSTRALIAN TAX DEDUCTED DIVIDEND PAID', 'RECORD DATE PAYMENT DATE', 'T 0000004 000 EXP',
    '3 March 2025 3 April 2025', '1 cent 2,000 A$20.00 A$0.00 A$20.00', '30% A$4.00 A$16.00 A$1.71',
]
EXPECT_AMP = ('EXP', datetime.date(2025, 4, 3), datetime.date(2025, 3, 3), D('20.00'), D('20.00'), D('0.00'), False)

TRUST_TOTALS = [
    'Sample Property Group Limited ABN 99 999 999 999', 'Sample Property Group Distribution/Dividend Advice - December 2024', 'Date: 28 February 2025', 'Payment Date:',
    'T 0000005 000 SPG', 'Total gross distribution & dividend', '*Total Australian tax withheld', 'Total net distribution & dividend',
    'SGT1 SPG 1,000 $0.0492 $49.20 $0.00 $49.20', 'SGT2 SPG 1,000 $0.0325 $32.50 $0.00 $32.50',
    'SPG 1,000 $0.0817 $81.70 $0.00 $81.70 $1.86',
]
EXPECT_TRUST = ('SPG', datetime.date(2025, 2, 28), None, D('81.70'), D('81.70'), D('0.00'), False)

PAYMENT_THEN_RECORD = [
    'HUBB LIMITED | ABN 66 666 666 666', 'Payment Date: Record Date:', 'TFN/ABN Status:', 'ASX Code:',
    '15 April 2025', '18 March 2025', 'Quoted', 'HUBB', 'Interim Dividend Statement', 'Gross Payment: $100.00',
    'Less Withholding Tax:', 'Net Payment: $100.00', '$0.00', '$0.20 $0.00 $100.00 500',
]
EXPECT_PAYMENT_THEN_RECORD = ('HUBB', datetime.date(2025, 4, 15), datetime.date(2025, 3, 18), D('100.00'), D('100.00'), D('0.00'), False)

WITH_WITHHOLDING = [line.replace('$50.00 $50.00', '$100.00 $100.00').replace('Less Withholding Tax $0.00', 'Less Withholding Tax $15.00')
                    .replace('Net Amount AUD 50.00', 'Net Amount AUD 85.00').replace('Direct Credit amount AUD 50.00', 'Direct Credit amount AUD 85.00')
                    .replace('amount of AUD 50.00', 'amount of AUD 85.00') for line in MUFG_STYLE]
EXPECT_WITHHOLDING = ('ACM', datetime.date(2025, 5, 12), datetime.date(2025, 4, 14), D('100.00'), D('85.00'), D('15.00'), False)

REINVESTED = MUFG_STYLE[:-2] + ['Dividend Reinvestment Plan amount AUD 50.00', 'Number of shares allotted: 5']
EXPECT_REINVESTED = ('ACM', datetime.date(2025, 5, 12), datetime.date(2025, 4, 14), D('50.00'), D('50.00'), D('0.00'), True)

ACCEPTED = {
    'mufg': (MUFG_STYLE, EXPECT_MUFG), 'computershare': (COMPUTERSHARE_LABELS_FIRST, EXPECT_COMPUTERSHARE),
    'label_first_net': (LABEL_FIRST_NET, EXPECT_LABEL_FIRST), 'value_per_line': (VALUE_PER_LINE, EXPECT_VALUE_PER_LINE),
    'amp_columns': (AMP_COLUMNS, EXPECT_AMP), 'trust_totals': (TRUST_TOTALS, EXPECT_TRUST),
    'payment_then_record': (PAYMENT_THEN_RECORD, EXPECT_PAYMENT_THEN_RECORD),
    'withholding': (WITH_WITHHOLDING, EXPECT_WITHHOLDING), 'reinvested': (REINVESTED, EXPECT_REINVESTED),
}

SCHEME_PAYMENT = ['Example Cement Limited ABN 77 777 777 777', 'Scheme Consideration Payment', 'The Scheme Consideration is $8.88 cash per share',
                  'Ordinary Shares $8.88 1,000 $8,880.00', 'Net Payment $8,880.00', 'Payment date: 9 July 2024']
BONUS_SHARE_PLAN = ['Example Bank Limited ABN 88 888 888 888', 'Bonus Share Plan Statement', 'Dividend Rate per Share 85 cents',
                    '1,000 shares x 85 cents = $850.00', 'Payment Date 2 July 2025']
UNKNOWN_LAYOUT = ['Dear customer', 'Your subscription has been renewed.', 'Total: $12.00', 'Date: 3 May 2025']
INCONSISTENT = [line.replace('Net Amount AUD 50.00', 'Net Amount AUD 40.00').replace('Direct Credit amount AUD 50.00', 'Direct Credit amount AUD 40.00')
                .replace('amount of AUD 50.00', 'amount of AUD 40.00') for line in MUFG_STYLE]
DISAGREEING_NET = [line.replace('Direct Credit amount AUD 50.00', 'Direct Credit amount AUD 49.00') for line in MUFG_STYLE]
NO_PAYMENT_DATE = [line for line in MUFG_STYLE if not line.startswith('Payment Date')]


# Revolut "Flexible Cash Funds" monthly statement (invented figures). Three daily returns of 0.5000 and three daily fees of
# 0.1800 (as the real statements print them: description line, then ISIN and amount on the next line).
def fund_statement(returns=('0.5000', '0.5000', '0.5000'), fees=('-0.1800', '-0.1800', '-0.1800'),
                   earned='1.5000', total_fees='-0.5400', period='Period Jun 1, 2025 - Jun 30, 2025'):
    lines = ['Flexible Cash Funds Statement', period, 'Generation date: Jul 2, 2025', 'MR TEST HOLDER', 'Germany',
             'Value, EUR', 'Opening Balance 1,000.00', 'Total Value purchased 0', 'Total Value sold 0',
             f'Total Earned Return {earned}', f'Total Fees {total_fees}', 'Total Withdrawn Return 0',
             'Total Reinvested Return 0', 'Closing Balance 1,000.96', 'Flexible Cash Funds - EUR',
             'Date Description Value Share price Shares']
    for day, (ret, fee) in enumerate(zip(returns, fees), start=1):
        lines += [f'Jun {day}, 2025, 3:03:17AM', 'Service Fee Charged EUR Class', f'IE0000TEST01 {fee}',
                  f'Jun {day}, 2025, 3:03:17AM', 'Return PAID EUR Class R', f'IE0000TEST01 {ret}']
    lines += ['Information about this Statement',
              'This statement is provided by Revolut Securities Europe UAB ("Revolut") in respect of your Flexible Cash Funds.']
    return lines


EXPECT_FUND = (datetime.date(2025, 6, 30), 'EUR', D('1.5000'), D('0.5400'), D('0.9600'))
