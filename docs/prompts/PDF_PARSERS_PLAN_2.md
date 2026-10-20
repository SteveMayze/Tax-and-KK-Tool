# PDF parsers for the Australian statements (Hodges, MECU, Ord Minnett): findings and development plan

Companion to `docs/prompts/PDF_PARSERS_PLAN.md` (ids G1 to G12 are defined there) and `docs/prompts/PHASES_4.md` (the Claude Code prompt). Written from a read-only review of `local/samples/Hodges`, `local/samples/MECU` and `local/samples/Ords`. This file contains structure, label text and counts only. No amounts, names, addresses, account numbers or property details from the samples.

## 1. Scope

| Folder | Files | Payer / organisation | Currency | Income to extract |
|---|---|---|---|---|
| Hodges | 11 monthly "Tax Invoice" statements | the managing agent's tenant/property payer name already used in the owner's database (read at run time; not in code) | AUD | rent received |
| MECU | 24 statements (one per month, a few multi-account) | `MECU` (fixed bank name) | AUD | interest, with overseas withholding tax where stated |
| Ords | 24 monthly or financial-year Cash Management Trust (CMT) statements plus one holdings snapshot | `Ord Minnett` (fixed name) | AUD | interest, withholding tax, and stock sales (recognised, see 4.3) |

Not income, never staged: transfers, BPAY, tax-office refunds, share-scheme consideration, property-sale proceeds, fees (fees are read only where they reduce an income payment, see Hodges).

## 2. Findings about the sample folders

1. **MECU file names are unreliable.** At least two files carry the other's statement number (one pair is swapped). Take the period from the content, never the file name; the inventory tool flags name/period mismatches (already built in Phase 15).
2. **pypdf cannot open any MECU file.** All 24 raise "Could not read Null object" while reading the cross-reference table, in strict and non-strict mode, in the pinned pypdf version. Poppler reads them. In the files checked the cross-reference subsection header declares one entry fewer than the table lists. Hodges and Ords open normally. This is a hard requirement of Phase 22 (see Q22.1).
3. **Overlap in Ords.** The two financial-year statements (June) repeat months that also exist as monthly statements, and are the only source of the June-quarter interest. Row-level de-duplication is needed (O3).
4. **The owner's hand-made CSV files are incomplete.** `mecu.csv` has no term-deposit interest (from the first maturity and monthly afterwards), and one withholding figure disagrees with both the statement and gross minus net. Rows already imported from these CSV files will collide with PDF rows under the duplicate rule (date + organisation + currency + gross). Phase 24 reports collisions and near-collisions; it does not delete anything.
5. **One large credit in Ords is a property sale**, not income. One stock sale is visible only as a proceeds transfer from a trading account with no contract note, so quantity, price and cost base cannot be read (O7).

## 3. Corner cases

### Hodges (rental statement, AUD)
- **A1 One-page tax invoice per month.** Structure: Money In, Money Out, You Received. Invariant: In - Out = Received. A statement that does not close is refused (G9).
- **A2 Rent lines wrap** over two lines (period text continues on the next line). Join by position, not by line count.
- **A3 Expense lines marked `*`** include GST. The `*` is read as a flag only; the app records no GST split.
- **A4 Other money-out lines:** management fee, a one-off sundry fee, repairs, owner withdrawal. Withdrawal is a payout of already-received rent and is never an expense of the income. Fees reduce net, they are not withholding.
- **A5 The statement "Total" line excludes the sundry fee.** Do not use it as the check; use the In/Out/Received invariant plus the listed lines.
- **A6 Two-month statement and short final period.** Period comes from the printed from/to dates, not a calendar month. One row per rent receipt period or one per statement (Q21.2).
- **A7 Rent arrears / part payments / paid-in-advance** lines: refuse unless described here (G12).
- **A8 Gross vs net.** Gross = rent received for the period, expenses = fees + charges listed as costs of the rental, withholding 0, net = gross - expenses. Check against "You Received" (before any owner withdrawal).

### MECU (bank statements, AUD)
- **M1 Multi-account statements.** Each statement lists several accounts; only interest-bearing sections matter. Account identity is never stored (masked).
- **M2 Dates have no year** ("Effective" and "Posted" columns). Derive the year from the statement period; handle December/January wrap.
- **M3 Interest Credit vs Bonus Interest** are separate lines: both are interest; the comment names the kind.
- **M4 Memo lines in parentheses.** "Overseas Withholding Tax" and "Gross Interest" appear as memo lines under a credit. They do not move the balance. Net credit = gross - withholding must hold, else refuse.
- **M5 Term deposits.** Interest at maturity is credited on one date; a later monthly term deposit pays by transfer into a savings account. Risk of counting the same interest twice (once in the TD section, once as the receiving credit). Rule: stage from the TD section only; the receiving credit is classified as a transfer when it matches (M5 test).
- **M6 Annual "Payment Summary for Withholding Tax"** in the June statement: used only as a cross-check of the year's gross interest and withholding; mismatch is a warning, not a refusal (the monthly figures win).
- **M7 Barcode-only extra pages** and a trailer page: no text, must not trigger the "no text layer" refusal for the whole file when other pages have text.
- **M8 Misnamed files** (finding 1).
- **M9 Running balance** per account: previous + credits - debits = balance. Failure refuses (G9).
- **M10 pypdf cannot read the file** (finding 2).

### Ord Minnett (CMT, AUD)
- **O1 Direction comes only from the running balance.** The statement prints a single amount column; whether a line is a credit or a debit is derived from the change in balance. A line whose sign cannot be proven refuses the statement.
- **O2 Quarterly interest plus a separate whole-dollar "Overseas Withholding Tax" debit**, usually on a different date. Pair by statement period and kind, not by adjacency. Gross = interest credit; withholding = the matching debit.
- **O3 Financial-year statements overlap monthly ones.** Dedupe at row level: same date + kind + amount = same row; first seen wins, the repeat is listed in the batch warnings. The FY-only June-quarter interest is staged from the FY file.
- **O4 Taxation summary table** (interest, withholding by year): cross-check only.
- **O5 CMT dividend credits duplicate the "Securities" advices.** Dividends are not staged from the CMT; they are recognised as covered elsewhere (notice).
- **O6 Other credits and debits, never income:** tax-office refunds, BPAY, transfers in/out, share-scheme consideration, property-sale proceeds. Classified by booking text; an unknown text refuses (G12).
- **O7 Stock sale seen only as a proceeds transfer** ("SELL ..." from a trading account). No quantity or price. Recognised and not imported: the notice shows only the date and that a sale proceeds transfer was seen (no security name, no amount). See Q23.3.
- **O8 `Portfolio_Valuation`** is a holdings snapshot: recognised, no income, nothing to import.
- **O9 Statement period and number** differ between monthly and FY layouts.
- **O10 Withholding without interest in the same statement** (interest in an earlier FY file): handled by O2/O3 pairing across the batch; if no partner is found, stage the withholding line as a warning, not a row.

## 4. Design

- New readers `hodges_rental`, `mecu_account`, `ordminnett_cmt`, registered in `statement_readers.READERS`. Recognition by structure, not by header text (G8).
- Organisation names: `MECU` and `Ord Minnett` fixed in `organisations.BANK_ORGANISATIONS`; the Hodges payer name is read from a configured setting, never from code.
- Currency AUD; amount parser US-style (`parse_amount_us`) with trailing `CR/DR` or sign variants as found; no new parsing dependency.
- No changes to the payment identity (gross = net + withholding + expenses) or to staging.
- Cross-statement logic (O3, O10, M5) lives in a batch step after all readers ran, with warnings only; it never mutates a single reader's rows except to drop exact duplicates.

## 5. Questions for the owner (each repeats in its phase)

1. Q21.1 Organisation for rent: the payer name already in the database (default) or the managing agent.
2. Q21.2 **Answered:** one row per statement.
3. Q21.3 **Answered:** fees as expenses of the rental.
4. Q22.1 **Answered:** a new dependency is approved if it causes no conflict (suggested: pikepdf, to be verified; fallback: pure-Python repair).
5. Q22.2 **Answered:** term-deposit interest staged from the TD section, category Interest.
6. Q22.3 Include Bonus Interest in the same row as the Interest Credit (default: separate rows).
7. Q23.1 **Answered:** pair withholding with the interest of the same quarter.
8. Q23.2 Property-sale credit: ignore (default) and confirm.
9. Q23.3 **Answered:** stock sales are out of scope (notice only).

## 6. Phase overview

| Phase | Content | Depends on |
|---|---|---|
| 21 | Hodges rental reader | 15 |
| 22 | MECU reader and tolerant PDF opening | 15, 22 requirement Q22.1 |
| 23 | Ord Minnett CMT reader, row-level dedupe | 15 |
| 24 | Cross-checks, collision report, close-out | 21 to 23 |

## 7. Test strategy

Same as the first plan: synthetic PDFs built in the test suite (`make_pdf`), invented names ("EXAMPLE AGENT", "EXAMPLE CREDIT UNION", "EXAMPLE BROKER"), invented figures worked out in the test file, one end-to-end test per reader, one test per corner-case id. The MECU opening problem gets a synthetic PDF whose cross-reference header is deliberately one short, generated in the test.

## 8. Risks

- The MECU repair may mask a truly damaged file: repair only the count mismatch, then require page text and a reconciling balance, else refuse.
- Dedupe in Ords could hide a real second payment of the same amount on the same date: only exact duplicates across overlapping statement periods are removed, and each is listed.
- Hand-made CSV rows already in the database may duplicate the PDF rows: reported, never auto-deleted.
