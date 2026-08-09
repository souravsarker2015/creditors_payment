# FinTrack — What This Project Is For

FinTrack is a personal finance tracker for someone managing money across several
informal, real-life ledgers at once — money lent and borrowed with people, salary
and other income, day-to-day spending, shared household costs, and running credit
at local shops. Each of those normally lives in a separate notebook or a
scattered set of phone notes; FinTrack gives them one place to live, per user
account, in English or Bangla.

It isn't a budgeting app or a double-entry accounting system — it's closer to a
digital version of the ledger books many households and small businesses
already keep, with the arithmetic, reminders, and reporting done automatically.

## Who it's for

Anyone tracking money relationships that don't go through a bank statement:

- Money you've lent to or borrowed from specific people, banks, or institutions
- Salary or other recurring income, and day-to-day expenses
- Household spending shared informally between family members
- Running credit at a local shop that gets settled up periodically
- Occasional contributions received from family, sponsors, or donors

## The modules

Each module is its own dashboard with a list of entities, a running balance, and a
full transaction history per entity (with year/month filtering).

### Creditors — money you owe
People, banks, or institutions you've borrowed from (Family, Bank, Microfinance,
Moneylender, Landlord, Supplier, etc.). Each creditor tracks Borrow/Repay
transactions, an optional due date (with Overdue / Due Soon badges), and optional
interest — a one-time fixed fee, or a recurring charge (Monthly / Every 3 Months /
Every 6 Months / Yearly) quoted as either a percentage of the balance or a flat
amount. Interest accrues as a live estimate only; you post it to the real balance
on demand, as an ordinary transaction.

### Debtors — money owed to you
The mirror image of Creditors: people who owe you money (Family, Client, Employee,
Tenant, Student, etc.), tracked via Lend/Receive transactions, with the same due
date and Overdue/Due Soon handling. No interest tracking here — none of the debtor
categories imply an interest-bearing loan.

### Income — what you earn
Income Sources (e.g. an employer, a client, a side gig) each with a running total
and a full history of individual payouts. Recurring schedules can auto-log salary
or any repeating payout on a cadence (Weekly, Every 2 Weeks, Monthly, Every 3
Months, Yearly) — including an option to shift the posting date to the previous
working day if it falls on a Friday or Saturday, for bank-paid salary that follows
that rule.

### Expense — what you spend
A chronological log of individual expenses, optionally grouped into categories
(Groceries, Transport, etc.), with the same kind of recurring-schedule support for
rent, subscriptions, and other repeating bills.

### Contributors — money received from others
Tracks contributions received from family, friends, sponsors, donors, investors,
or organizations — useful for tracking gifts, funding, or support that isn't a
loan and isn't income from work.

### Household (Bazar) — shared household spending
Day-to-day household purchases (bazar), optionally grouped by category
(Groceries, Fish, etc.) and optionally attributed to a household member who
fronted the money personally. A member's fronted purchases accumulate as a
balance owed back to them, separate from settlements already paid out — so
"who paid for what" and "who's owed what back" stay straight even when several
people are buying groceries out of pocket.

### Shops — running credit at local shops
Tracks shops you buy from on credit — a running tab per shop across
Grocery, Pharmacy, Vegetable & Fruit, Pharmacy, Hardware, Electronics, and similar
categories — recording what's been put on credit versus what's been paid back.

### Net Worth — the whole picture at once
A single rollup page combining all six ledgers into two halves that are
deliberately kept separate rather than blended into one number:
- **Balances** (a snapshot right now): what's owed to you minus what you owe
  across Creditors, Shop Dues, and Household Members.
- **Lifetime Cash Flow** (all-time totals): everything ever earned or received
  minus everything ever spent.
- **Overall Net Position**: the sum of both, as the headline figure.

It carefully avoids double-counting a household purchase a member fronted (counted
once, as their balance — not again as spending), and leaves out interest that has
merely accrued but hasn't been posted to a real balance yet.

## Features that apply across every module

- **CSV export and bulk import** on every list, including an opening-balance
  column so an existing spreadsheet ledger can be migrated in with its current
  balances intact.
- **PDF statements** — a print-optimized, always-light-themed page per entity for
  saving or handing someone a paper record.
- **Year/month filtering, sorting, and pagination** on every list and history.
- **Monthly trend charts and category breakdowns** on every dashboard.
- **Due-date reminders** (Overdue / Due Soon) wherever a due date makes sense.
- **Recurring transactions** for Income and Expense, generated automatically the
  next time you visit the relevant dashboard — no background service required.
- **Full Bangla and English localization**, switchable per user at any time.
- **Light/dark mode with a choice of three accent palettes**, persisted per user.
- **Per-user accounts** — everything above is scoped to the logged-in user; two
  people's ledgers never mix.

## Getting started as a user

1. Log in (an account is created for you with sensible theme/language defaults).
2. In whichever module applies, add the people/sources/categories you deal with
   (a creditor, an income source, a shop, etc.) — or bulk-import them from a CSV
   if you're migrating from an existing spreadsheet.
3. Record transactions against them as money moves, or set up a recurring
   schedule for anything that repeats on its own (salary, rent, a subscription).
4. Check each module's dashboard for balances, trends, and anything overdue; check
   **Net Worth** for the picture across all of them at once.
