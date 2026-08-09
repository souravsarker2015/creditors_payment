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
- **Test suite repaired — 16 of 60 tests were silently failing, now 115/115 pass** — a fresh
  re-inspection (actually running `manage.py test`, not just re-reading old notes) found the
  checked-in suite had drifted out of sync with two already-shipped features: 13 tests
  (`CreditorCategoryTests`, `DebtorCategoryTests`, `HouseholdViewTests`) read
  `response.context["creditors"]`/`["debtors"]`/`["categories"]`/`["members"]` directly, but
  pagination had already moved list results into `response.context["page_obj"]`, so those keys no
  longer existed; 1 (`IncomeFilterTests`) asserted the pre-year-filter meaning of
  `total_source_income`, which year/month filtering had deliberately redefined as an all-time
  total (with the filtered figure moved to a separate `period_income` field). Neither was a real
  app bug — the views were correct the whole time — but a 27%-red suite trains everyone to ignore
  failures, which is exactly when a real regression slips through. Fixed all 16, then added
  substantial new coverage that hadn't existed for anything shipped since the original review:
  due-date/overdue/due-soon logic (Creditors, Debtors, and now Shops), interest accrual and
  proration across every type/basis combination plus posting semantics, the full recurring-
  transaction engine (catch-up, the generation cap and its continuation, pause/resume, month-end
  clamping, the weekend-shift rule and its no-drift anchor invariant), and the net worth page's
  calculations including its double-counting-avoidance case and cross-user isolation. The suite
  went from 60 tests (16 broken) to 115 tests, all passing.
- **Every delete/pause/resume action converted from a GET link to a POST-only endpoint** — all
  11 views that previously ran immediately when their URL was visited
  (`transaction_delete_view` ×5, `purchase_delete_view`, `settlement_delete_view`,
  `expense_delete_view`, `recurring_income_toggle_view`, `recurring_income_delete_view`,
  `recurring_expense_toggle_view`, `recurring_expense_delete_view`) are now decorated
  `@require_POST` and rejected with 405 on GET, closing off the risk of an email client
  prefetching a link, a browser link-preview, or a stray `<img src="...">` silently triggering a
  delete. Every template that linked to one of these now submits a small CSRF-protected `<form>`
  instead of a bare `<a href>`, styled identically to the link it replaced so nothing changes
  visually. Verified end-to-end: GET now returns 405 and leaves the record untouched, POST still
  works, and the rendered pages actually emit `<form method="post">` rather than a plain link.
- **Shops (বাকি) picked up the same due-date/reminder treatment as Creditors and Debtors** — an
  optional `due_date` field, Overdue/Due-Soon badges on the shop's detail page and list card, and
  a "Needs Attention" panel on the Shops dashboard — identical logic and presentation to the
  Creditors/Debtors version, closing a consistency gap where running shop credit (conceptually the
  same kind of payable as a Creditor) had no reminder support at all.
- **Free-text name search added to the three list pages that were missing it** — Income Sources,
  Expense Categories, and Household Members now have the same `?q=` search-by-name box that
  Creditors, Debtors, Contributors, and Shops already had, so search is now consistent across
  every entity list in the app.

## Suggested / not yet implemented

- **No self-service password recovery, and signup is open to anyone** (Low–Medium — reviewed and
  deliberately deferred)
  `signup_view` uses Django's stock `UserCreationForm` with no invite code, email verification, or
  CAPTCHA — anyone who finds the URL can create an account. There's no
  `password_reset`/`password_reset_confirm` flow at all, and production has no `EMAIL_BACKEND`
  configured (only `dev.py` does, pointed at the console), so today a locked-out user has exactly
  one recovery path: asking whoever has Django Admin access to reset their password by hand. This
  was raised and explicitly deferred rather than left as an unexamined gap — the options remain
  either adding Django's built-in email-based password-reset flow (needs a real `EMAIL_BACKEND` in
  `prod.py`, e.g. SMTP or a transactional-email API) or gating signup behind an invite/access code
  if public self-registration was never actually intended. Worth revisiting once there's an actual
  email-sending setup decided on.

## Platform

- **Basic REST API** (High)
  Would enable a future mobile client, but only worth the effort if that's actually on the
  roadmap — otherwise it's speculative scope.

## Suggested priority

With the test suite repaired and substantially expanded, the GET-based delete/toggle views closed
off, the Shops due-date gap filled, and search made consistent everywhere, what's left is
password recovery (a deliberate, deferred decision — pick it up once an email-sending setup is
chosen) and the REST API (speculative scope, worth it only once a concrete need like a mobile
client is driving it).
