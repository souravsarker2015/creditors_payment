# Project Review & Suggestions

These are recommendations only — **none of this has been implemented**. They come out of a
full inspection of the app (creditors, debtors, contributors, income, expense) done alongside
adding search/filtering and the dashboard chart redesign. Each item notes why it's useful, who
it helps, and a rough complexity estimate.

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
  Creditors, Debtors, Income, and Expense are four separate dashboards today; nothing rolls
  them into one "you owe X, are owed Y, earned Z, spent W → net position" view. A single
  summary page (or a card on the main dashboard) would give an at-a-glance financial picture.

- **CSV export** (Low)
  For taxes/bookkeeping, a "download as CSV" button on each list (creditors, debtors, expenses,
  income, contributions) is cheap to add and high-value for anyone doing manual reconciliation.

## Usability / productivity

- **Pagination on Creditors / Debtors / Contributors lists** (Low)
  The Expense app already has a solid paginator (`Paginator` + windowed page links via
  `_build_pagination_window`); the other three list views currently load everything
  unbounded. Worth reusing that existing pattern once record counts grow past a page or two.

- **Sorting options** (Low)
  Lists are hardcoded to sort by name. Letting users sort by amount owed/remaining or last
  activity date would help once someone has more than a handful of creditors/debtors.

- **Bulk CSV import for creditors/debtors** (Medium)
  Useful for users migrating an existing spreadsheet of who-owes-who into the app instead of
  re-entering everyone by hand.

## Reporting

- **Monthly/yearly trend charts** (Medium)
  Everything currently is a point-in-time snapshot (donut breakdowns). A line/bar chart of
  borrowed/repaid or income/expense over time would round out the analytics story alongside
  the redesigned donut charts.

- **PDF statement per creditor/debtor** (Medium)
  A printable ledger for a specific person is a common real-world need ("send me a statement
  of what I owe you") and maps naturally onto the existing detail-page transaction history.

## Platform

- **Recurring transactions** (Medium)
  For recurring income (salary) or recurring expenses (rent, subscriptions), auto-creating
  entries on a schedule would save repetitive manual entry.

- **Basic REST API** (High)
  Would enable a future mobile client, but only worth the effort if that's actually on the
  roadmap — otherwise it's speculative scope.

## Suggested priority

Due-date reminders, CSV export, and pagination are the cheapest wins with the clearest
day-to-day payoff for a personal finance tracker, and would be a reasonable next batch of work
ahead of the higher-complexity items (interest tracking, recurring transactions, API).
