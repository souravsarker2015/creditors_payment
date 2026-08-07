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
- **Net worth overview** — a new "Net Worth" page (top of the nav, new `apps.overview` app at
  `/networth/`) rolls up all six ledgers into one picture, split into two halves that are
  deliberately never blended into a single blind sum:
  - **Balances** (a point-in-time snapshot): Receivables (Debtors) minus Payables (Creditors +
    Shop Dues + Household Members' outstanding balance) = **Net Balance**.
  - **Lifetime Cash Flow** (all-time totals, not a balance): Income + Contributors received,
    minus Expense + household spending = **Net Cash Flow**.
  - **Overall Net Position** = Net Balance + Net Cash Flow, shown as the headline figure.

  The one real accounting trap here — a household purchase a member fronted would otherwise get
  counted twice (once as that member's payable, again as "spending") — is avoided by only folding
  household purchases into the Cash Flow side when nobody fronted them (`buyer` unset); a
  member-fronted purchase is represented exactly once, via that member's balance. Accrued-but-
  unposted interest is intentionally excluded, consistent with how it's already kept out of every
  other balance in the app. Verified against hand-seeded data across all six ledgers, including a
  purpose-built case for the double-counting trap and a check that two users' figures never leak
  into each other.
- **Recurring transactions** — Income and Expense each have a "Recurring" schedule list
  (linked from their dashboards) for things like salary, rent, or a subscription: pick a source
  (Income) or category (Expense, optional), an amount, a frequency (Weekly, Every 2 Weeks,
  Monthly, Every 3 Months, or Yearly), and a next-occurrence date. From then on that entry is
  created automatically — no background worker or server cron involved, since PythonAnywhere's
  free/standard tiers don't reliably offer one and this deploys there. Instead, every visit to the
  Income or Expense dashboard or list page opportunistically catches up any schedule that's come
  due, generating one transaction per missed occurrence (dated on the occurrence, not on today) up
  to a 60-occurrence cap per visit so a very stale schedule can't block a page load; any remainder
  finishes on the next visit. Monthly/quarterly/yearly math clamps to the last real day of the
  target month (e.g. Jan 31 → Feb 28/29), and each generated entry links back to the schedule that
  created it, visible via a badge, without your ever needing to think about it. A schedule can be
  paused (stops generating, keeps its history) or resumed, and edited or deleted at any time;
  deleting a schedule only stops future generation — entries it already created stay exactly as
  they are, since they're now ordinary transactions like any other. A one-time toast on the
  dashboard confirms how many entries were just auto-generated, if any were. Each schedule also
  has an optional "move to the previous working day if this falls on a Friday or Saturday" toggle,
  off by default, for things like bank-paid salary that skip the weekend (Bangladesh's Fri–Sat) —
  e.g. a salary anchored to the 24th posts on the 23rd if the 24th is a Friday, or the 22nd if it's
  a Saturday. The schedule's own anchor date never moves (it stays on the 24th every month); only
  the generated entry's date shifts, so the rule can't drift the schedule earlier over time.
  Verified with seeded data covering multi-period catch-up, the generation cap and its
  continuation on a follow-up visit, pause/resume, month-end date clamping across leap and
  non-leap years, cross-user isolation, and the weekend-shift rule (Friday and Saturday cases,
  the no-drift anchor invariant, and the opt-in default staying off).

## Platform

- **Basic REST API** (High)
  Would enable a future mobile client, but only worth the effort if that's actually on the
  roadmap — otherwise it's speculative scope.

## Suggested priority

With CSV export/import, theming, full localization, year/month filters, trend charts, PDF
statements, pagination/sorting, due-date reminders, interest tracking, the net worth overview, and
recurring transactions all shipped, what's left is a single Platform-level item: a REST API — worth
picking up only once there's a concrete need driving it (e.g. a mobile client), since it's more
about enabling future capability than fixing a current gap.
