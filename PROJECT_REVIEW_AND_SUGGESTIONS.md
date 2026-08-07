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
- **Monthly trend charts** — every dashboard (all seven apps) now has a rolling-12-months bar
  chart below the existing donut breakdown (grouped bars for two-series apps like
  Borrowed/Repaid, a single series for one-metric apps like Total Spent), via a shared
  `renderTrendChart()` helper in `charts.js`.
- **PDF statements** — every entity with a transaction history (Creditor, Debtor, Income Source,
  Contributor, Shop, Household Member) has a "Statement" link next to Export CSV, opening a
  print-optimized page (always light-themed, regardless of the app's dark/light setting) with
  entity info, all-time summary figures, and the full transaction table. A "Print / Save as PDF"
  button uses the browser's native print-to-PDF — no new server dependency. Respects the same
  Year/Month filter as the detail page, so a single-month statement is one click away.
- **Pagination on every list page** — Creditors, Debtors, Contributors, and Income Sources now
  paginate like Expense/Household/Shop Dues already did; Household Members picked up pagination
  too. Bazar Categories stays unpaginated on purpose since that page's donut chart needs every
  category at once.
- **Sorting on every list page** — each list (all seven apps) has a "Sort by" control: name A–Z/Z–A
  plus a domain-relevant amount sort (remaining balance for Creditors/Debtors/Shop Dues, total
  given/earned/spent for Contributors/Income Sources/Bazar Categories, date/amount for the
  Expense log, month/total for the Bazar Log). Selection persists across pagination.
- **Bulk CSV import** — every entity-creation list (Creditors, Debtors, Shop Dues, Contributors,
  Income Sources, Household Members, Bazar Categories, Expense Categories) has an "Import CSV"
  button next to "New …" plus a "Template" link that downloads a starter CSV with the right
  headers. Rows are matched case-insensitively against existing names and duplicates/blanks are
  skipped rather than erroring the whole file; a summary ("Imported N, skipped N") is shown after
  upload. For the balance-carrying entities (Creditors, Debtors, Shop Dues, Contributors, Income
  Sources) an optional "Opening Balance" column seeds one initial transaction, so migrating an
  existing who-owes-who spreadsheet brings the current balances across, not just the names.

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

## Platform

- **Recurring transactions** (Medium)
  For recurring income (salary) or recurring expenses (rent, subscriptions), auto-creating
  entries on a schedule would save repetitive manual entry.

- **Basic REST API** (High)
  Would enable a future mobile client, but only worth the effort if that's actually on the
  roadmap — otherwise it's speculative scope.

## Suggested priority

With CSV export/import, theming, full localization, year/month filters, trend charts, PDF
statements, and pagination/sorting across every list all shipped, the cheapest remaining win is
due-date reminders — a small, isolated change with clear day-to-day payoff. The heavier items
(interest tracking, net worth overview, recurring transactions, a REST API) are worth revisiting
once that's in, roughly in that order.
