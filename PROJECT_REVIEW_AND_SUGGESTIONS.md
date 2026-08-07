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
- **Due dates + reminders** — Creditors and Debtors both have an optional `due_date` field
  (set from the edit form, with the same flatpickr date picker used elsewhere). Any entity with
  an unpaid balance and a due date shows an "Overdue" or "Due Soon" (within 7 days) badge on its
  list card and detail page, and both dashboards surface a "Needs Attention" panel listing
  everyone overdue or coming due, soonest first.
- **Interest tracking for loans** — Creditors have an optional `interest_type`: Fixed Amount
  (One-Time), Monthly, Every 3 Months, Every 6 Months, or Yearly. The one-time Fixed Amount is a
  single flat ৳ figure with no time component. The four period types additionally take an
  `interest_basis` — **Percentage** (rate % of the outstanding balance) or **Fixed Amount** (a
  flat ৳ figure repeated every period, e.g. "৳500 every month" instead of a rate) — so any period
  can be quoted either way, matching how real lenders phrase terms. Both bases accrue
  proportionally to actual days elapsed since the last transaction (e.g. Monthly uses a ~30-day
  period, Yearly ~365) rather than jumping in whole-period steps. The edit form shows only the
  fields relevant to the current type/basis combination, swapped live via Alpine as they change.
  The detail page shows a clearly-separated "Interest" card — rate/amount, accrued interest, and
  a "Balance Incl. Interest" total — as a live estimate only; the headline
  "Outstanding Balance" figure, list cards, dashboard totals, CSV exports, and statements are all
  completely untouched by it. A "Post to Balance" button (shown only when something has actually
  accrued) capitalizes it into the ledger as a real, auditable BORROW transaction on demand — the
  amount is always recomputed server-side at the moment of posting, never trusted from the page,
  and nothing is ever posted automatically. Posting a one-time Fixed Amount charge clears it
  afterwards so the same flat fee can't be posted twice by accident; a periodic Fixed Amount
  basis (e.g. ৳500/month) keeps recurring like a rate does, only resetting its accrual clock.
  Deliberately scoped to Creditors only,
  since none of the Debtor categories imply interest-bearing debt.

## Finance / accounting value

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
statements, pagination/sorting, due-date reminders, and interest tracking all shipped, what's
left is the more speculative, larger-scope items: a net worth overview, recurring transactions,
and a REST API — worth picking up in roughly that order, each only once there's a concrete need
driving it.
