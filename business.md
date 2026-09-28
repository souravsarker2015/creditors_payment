# ROLE
You are a senior Django architect. You are adding a new, fully separate "Business" module to my
EXISTING Django project. Your top priority is NOT breaking anything that already works.

# STEP 0 — UNDERSTAND BEFORE YOU WRITE ANY CODE
Before writing code, inspect the project and report back to me:
1. Django version, settings layout, INSTALLED_APPS, and how apps are organized under `apps/`.
2. The user model (custom `AUTH_USER_MODEL` or default), existing roles/groups/permissions,
   and how the current "creditor dashboard" handles login, redirects, and access control.
3. Frontend approach (Django templates / HTMX / DRF + [Next.js/React]), base templates,
   CSS framework, and how the existing sidebar/navigation is built.
4. Database engine, migration state (`showmigrations`), and any custom middleware.
Then give me a short implementation plan and WAIT for my approval.

# NON-BREAKING RULES (mandatory)
- Do NOT modify existing models, migrations, URLs, views, or templates, except for these
  minimal, clearly marked hooks:
  (a) adding the new apps to INSTALLED_APPS,
  (b) one `include()` line in the root urls.py,
  (c) one "Switch Dashboard" entry in the existing navigation.
- All new models live in the new apps with their own migrations. No FK changes on existing
  tables. Link to users only through `settings.AUTH_USER_MODEL`.
- Every new app gets a unique `label` in its AppConfig (e.g. `business_ponds`) to avoid clashes.
- All business URLs live under `/business/` with namespaced routes.
- Run `makemigrations --check`, the existing test suite, and `check --deploy` before and after,
  and show me the results.
- Commit in small, reviewable steps. List every existing file you touched.

# FOLDER STRUCTURE
```
apps/
  business/
    __init__.py
    core/          # shared base models, dashboard access, units, settings, mixins
    ponds/         # ponds and culture cycles
    species/       # fish types
    suppliers/     # feed suppliers and feed products
    feed/          # purchases, stock, usage per pond
    markets/       # fish markets / wholesale depots (aarot) and buyers
    sales/         # fish sales
    credit/        # credit ledger (payable and receivable)
    finance/       # income and expense (business + household/personal)
    reports/       # dashboards and reports
```
Each sub-app is a normal Django app, registered as `apps.business.<name>`.

# 1. DASHBOARD ACCESS AND SWITCHING
- Model `Dashboard` (code, name, url_name, icon, is_active, order). Seed with
  "creditor" (the existing one) and "business".
- Model `UserDashboardAccess` (user, dashboard, is_default, granted_by, granted_at).
- Rules:
  - Superusers/admins can access every dashboard and switch freely.
  - Admins assign which users can access which dashboards from an admin UI page
    (not only Django admin).
  - Normal users only see dashboards assigned to them. With exactly one, go straight there.
- Store the active dashboard in the session. Provide a dashboard switcher (dropdown in
  the top bar) visible only when the user has 2 or more dashboards.
- Protect every business view with a reusable mixin/decorator `business_access_required`
  and return 403 (not a crash) if access is missing.
- The existing creditor dashboard's behaviour for current users must stay exactly the same.

# 2. BASE MODEL (in business/core)
Abstract `BusinessBaseModel`: created_at, updated_at, created_by, updated_by, is_active,
notes, plus soft delete (is_deleted, deleted_at) with a default manager that hides deleted rows.
All money uses `DecimalField(max_digits=14, decimal_places=2)`. Currency is BDT (৳).

# 3. UNITS (fully dynamic)
- `Unit` (name, symbol, unit_type: weight/count/volume/other, is_base).
- `UnitConversion` (from_unit, to_unit, factor), editable by the admin.
- Seed data: kg (base weight), gram, mon/maund (default 40 kg, editable because local
  practice varies), piece, and others.
- Every quantity field stores: quantity, unit, AND an auto-calculated `base_quantity`
  (in kg for weight) so reports can compare across units.
- The user can add new units from the UI at any time.

# 4. PONDS AND CULTURE CYCLES
- `Pond`: name/code, location, area (value + unit such as decimal/bigha/acre), depth,
  ownership (own/leased), lease amount and period, status, photo.
- `CultureCycle` (one pond, one season/batch): start date, expected harvest date, status.
- `Stocking`: cycle, species, fingerling quantity (count and/or weight), size, source,
  cost per unit, total cost.
- `Mortality` log and optional `SampleWeighing` (average weight over time).
- `Harvest`: cycle, species, quantity + unit, date, and a link to the sale(s).
- Per-pond and per-cycle profit and loss: stocking + feed + labour + other costs vs sales.

# 5. FISH SPECIES
`Species` (name in English and Bangla, e.g. Rui/রুই, Katla/কাতলা, Pangas/পাঙ্গাস,
Tilapia/তেলাপিয়া), with a default selling unit. Fully user-manageable.

# 6. SUPPLIERS AND FEED
- `Supplier`: name, phone, address, contact person, opening balance (payable/receivable).
- `FeedProduct`: brand, type (floating/sinking/starter/grower), bag size + unit,
  default price, supplier(s).
- `FeedPurchase` (header + line items): supplier, date, invoice no., items, quantity + unit,
  rate, discount, transport cost, total, paid now, due amount, payment type (cash/credit/partial).
- `FeedStock`: auto-calculated from purchases minus usage (never edited by hand).
- `FeedUsage`: date, pond/cycle, feed product, quantity + unit (supports daily entry and
  bulk entry for several ponds at once).
- Low-stock alert with a configurable threshold.

# 7. MARKETS, BUYERS AND SALES
- `Market` (wholesale fish market / aarot): name, location, commission % or fixed rate,
  default deductions.
- `Buyer` (wholesaler/aratdar/paikar): name, phone, market, opening balance.
- `FishSale` (header + lines): date, market, buyer, pond/cycle (optional), and per line:
  species, quantity + unit (mon/kg/piece/etc.), rate per unit, gross amount.
  Deductions: commission, labour, transport, toll/khajna, ice, others (dynamic list).
  Net amount, amount received, amount due.
- A sale can be linked to a harvest so pond-level P&L stays correct.

# 8. CREDIT LEDGER ("baki" — the core of my business)
We take feed on credit and repay after selling fish. We may also give feed/money on credit
to others. Build ONE generic ledger that handles both directions:
- `Party` concept covering suppliers, buyers, and other people (use a GenericForeignKey
  or a unified Party model — recommend the better option to me).
- `LedgerEntry`: party, date, direction (payable/receivable), source (purchase, sale,
  loan given, loan taken, repayment, adjustment), amount, reference document, running balance.
- `Repayment`: pay fully or partially; a payment can be linked to a specific sale
  ("repaid from the sale on DD/MM").
- Party statement page: opening balance, all transactions, running balance, closing
  balance, printable/PDF, and a shareable summary.
- Due list: who owes me and whom I owe, with ageing (0–30, 31–60, 61–90, 90+ days).
- Optional due date and reminders.

# 9. INCOME AND EXPENSE (business + personal/household)
- `Category` is hierarchical (parent/child) and fully user-defined, with a type
  (income/expense) and a scope (business/household/personal). Seed examples:
  - Business expense: labour, electricity, medicine, lime/fertilizer, pond lease, transport, repairs
  - Household: groceries, utilities, rent, medical
  - Children: school fees, tuition, books, clothing
  - Income: fish sales (auto), other income
- `Account` (cash, bank, bKash/Nagad, etc.) with balances and transfers between accounts.
- `Transaction`: date, category, account, amount, description, optional pond/cycle,
  optional family member, receipt attachment.
- Recurring transactions (monthly rent, school fees).
- Monthly budget per category with actual vs budget.

# 10. REPORTS AND DASHBOARD
Business dashboard home with cards and charts:
- Today / this month / this year: sales, feed purchases, expenses, net profit.
- Total payable vs receivable, top dues.
- Feed stock status and low-stock alerts.
- Active cycles per pond with days running and cost so far.
- Charts: monthly sales vs expenses, sales by species, sales by market,
  expense breakdown by category.
Reports (filter by date range, pond, species, market, party, category; export to Excel/PDF):
pond-wise P&L, cycle P&L, species-wise sales, market-wise sales, feed consumption and
FCR (feed conversion ratio), party ledger, due/ageing, income-expense statement,
household vs business spending.

# 11. USER-FRIENDLINESS REQUIREMENTS (very important)
- Mobile-first responsive UI; most entries will be made from a phone at the pond or market.
- Quick-entry forms with sensible defaults (today's date, last-used market/buyer/unit).
- Searchable dropdowns with "+ Add new" inline (add a supplier/unit/category without
  leaving the form).
- Line items added/removed dynamically; totals calculated live on the page.
- Show quantity in the chosen unit AND converted (e.g. "5 mon = 200 kg").
- Bangla and English support via Django i18n, with a language toggle;
  BDT formatting with Bangladeshi number grouping (e.g. ৳ 1,25,000).
- Clear success/error messages; confirmation before delete; soft delete with restore.
- Print-friendly invoices and statements.
- Everything configurable from the UI — no hard-coded species, units, markets,
  categories, or deduction types.

# 12. PERMISSIONS
Beyond dashboard access, use Django permissions/groups inside the business module
(e.g. can view reports, can add sales, can manage settings), so an admin can give a
staff member data-entry access without letting them see profit reports or household expenses.

# 13. QUALITY
- Service layer for business logic (stock calculation, ledger posting, P&L) — keep views thin.
- Use `transaction.atomic()` for anything that posts to more than one table
  (e.g. a sale creating ledger entries).
- Database indexes on date, party, pond, and category fields.
- Unit tests for: unit conversion, stock calculation, ledger balance, P&L, and access control.
- Seed/fixture command: `python manage.py seed_business` for units, species, and categories.
- Audit trail for create/update/delete on financial records.

# DELIVERY PHASES (wait for my review after each)
1. Core: folder structure, base model, dashboard access + switcher, units.
2. Master data: ponds, species, suppliers, feed products, markets, buyers, categories, accounts.
3. Transactions: stocking, feed purchase/usage, sales, harvest.
4. Credit ledger and repayments.
5. Income/expense and budgets.
6. Dashboard, reports, exports.
7. i18n (Bangla), polish, and tests.

Before Phase 1, ask me any clarifying questions you need, especially about:
[my frontend stack], [how the creditor dashboard currently checks access],
[whether multiple businesses/owners should be supported in future], and
[the default kg value of 1 mon I use].