# Project Review & Suggestions

These are recommendations only — the "Suggested / not yet implemented" section below reflects
what's still open. The "Implemented since this review" section tracks what's shipped since the
original inspection, so this file doesn't go stale. Each remaining item notes why it's useful,
who it helps, and a rough complexity estimate.

Scope is now seven apps: creditors, debtors, contributors, income, expense, household (bazar),
and shops (বাকি tracking) — household and shops didn't exist at the time of the original review.

## Implemented since this review

- **CSV export** — every list page (Creditors, Debtors, Shop Dues, Contributors, Income Sources,
  Household Members, Bazar Categories, Bazar Log, Expense Log) and every transaction-history
  detail page (Creditor, Debtor, Income Source, Contributor, Shop, Household Member) has an
  Export CSV button that respects whatever filter is currently active. UTF-8 BOM included so
  Bangla names/notes render correctly in Excel.
- **Year/Month filtering with period stats** — the six transaction-history detail pages let you
  narrow to a specific year or month; the all-time stat cards (Outstanding Balance, Cumulative
  Revenue, etc.) stay as true running totals, and a separate "this period" line shows the
  filtered sums. The Bazar Categories page reuses the same filter plus a spending-by-category
  donut chart and per-category % share.
- **Full theming system** — light/dark mode × 3 accent palettes (Ledger Teal, Indigo Classic,
  Slate Mono), persisted per-user, switchable from both the desktop topbar and a touch-sized
  panel in the mobile menu.
- **Full Bangla localization** — every template and Python-side message across all seven apps,
  with a real `.po`/`.mo` translation set (not machine-generated placeholders), language
  switchable per-user and applied server-side via Django's i18n.
- **Household (bazar) and Shops (বাকি) apps** — full CRUD, dashboards, and category/member
  tracking, built to match the existing Creditors/Debtors patterns.
- **Mobile responsiveness pass** — fixed touch-target sizing and a topbar that was overflowing
  on phones; verified table/filter/pagination layouts collapse correctly at narrow widths.
- Assorted correctness fixes surfaced during this work: the Paid/Unpaid filter's confusing
  shared-variable bug, a missing Flatpickr stylesheet that broke every date picker, and an
  `UnboundLocalError` on household purchase submission caused by a variable named `_` shadowing
  the translation function.

## Finance / accounting value

- **Due dates + reminders on debts** (Medium)
  Creditor/Debtor transactions have no due date today, so nothing tells you a repayment is
  coming up. Add an optional `due_date` to `Transaction`/`Debtor` and surface a "due soon /
  overdue" badge on the dashboards and list cards.

- **Interest tracking for loans** (Medium–High)
  Categories like `BANK`, `MICROFINANCE`, and `MONEYLENDER` imply interest-bearing debt, but
  there's no rate or accrual logic anywhere in the model. Even a simple flat/simple-interest
  field per creditor would materially improve accuracy for real loans.

- **Net worth / consolidated overview** (Low–Medium)
  Creditors, Debtors, Income, Expense, Household, and Shops are six separate dashboards today;
  nothing rolls them into one "you owe X, are owed Y, earned Z, spent W → net position" view.
  A single summary page (or a card on the main dashboard) would give an at-a-glance financial
  picture across the whole app, not just one ledger at a time.

## Usability / productivity

- **Pagination on Creditors / Debtors / Contributors / Income Sources lists** (Low)
  Expense, Household (Bazar Log), and Shop Dues already have a solid paginator (`Paginator` +
  windowed page links via `_build_pagination_window`); these four list views still load
  everything unbounded. Worth reusing that existing pattern once record counts grow past a page
  or two.

- **Sorting options** (Low)
  Lists are hardcoded to sort by name (or, for Shop Dues/Bazar Categories, by amount). Letting
  users choose the sort — amount owed/remaining, last activity date — would help once someone
  has more than a handful of entries.

- **Bulk CSV import for creditors/debtors** (Medium)
  Useful for users migrating an existing spreadsheet of who-owes-who into the app instead of
  re-entering everyone by hand. Pairs naturally with the CSV export now in place — same column
  shape, reverse direction.

## Reporting

- **Monthly/yearly trend charts** (Medium)
  The donut breakdowns and the new Year/Month filter are both point-in-time or single-period
  snapshots. A line/bar chart of borrowed/repaid or income/expense *over* time (e.g. last 12
  months trended) would round out the analytics story.

- **PDF statement per creditor/debtor** (Medium)
  A printable ledger for a specific person is a common real-world need ("send me a statement
  of what I owe you") and maps naturally onto the existing detail-page transaction history —
  and now onto its CSV export, which could feed a PDF template directly.

## Platform

- **Recurring transactions** (Medium)
  For recurring income (salary) or recurring expenses (rent, subscriptions), auto-creating
  entries on a schedule would save repetitive manual entry.

- **Basic REST API** (High)
  Would enable a future mobile client, but only worth the effort if that's actually on the
  roadmap — otherwise it's speculative scope.

## Suggested priority

With CSV export, theming, full localization, and the year/month filters now shipped, the
cheapest remaining wins are pagination on the four still-unbounded lists and due-date
reminders — both small, isolated changes with clear day-to-day payoff. Bulk CSV import is a
natural next step given export already defines the column shape. The heavier items (interest
tracking, trend charts, PDF statements, recurring transactions, a REST API) are worth revisiting
once those are in, roughly in that order.
