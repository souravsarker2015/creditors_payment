from datetime import date

from .models import Account, AccountKind, Category, CategoryType, Scope

E, I = CategoryType.EXPENSE, CategoryType.INCOME
B, H = Scope.BUSINESS, Scope.HOUSEHOLD

# (name, Bangla, type, scope, [(child, child Bangla)], system)
DEFAULT_CATEGORIES = [
    ("Labour", "শ্রমিক", E, B, [("Daily labour", "দিনমজুর"), ("Salaries", "বেতন")], False),
    ("Electricity", "বিদ্যুৎ", E, B, [], False),
    ("Fuel / diesel", "জ্বালানি / ডিজেল", E, B, [], False),
    ("Medicine & treatment", "ওষুধ ও চিকিৎসা", E, B, [], False),
    ("Lime & fertilizer", "চুন ও সার", E, B, [], False),
    ("Pond lease", "পুকুর লিজ", E, B, [], False),
    ("Transport", "পরিবহন", E, B, [], False),
    ("Repairs & equipment", "মেরামত ও যন্ত্রপাতি", E, B, [("Nets", "জাল"), ("Aerator / pump", "এয়ারেটর / পাম্প")], False),
    ("Other farm costs", "খামারের অন্যান্য খরচ", E, B, [], False),
    ("Fish sales", "মাছ বিক্রি", I, B, [], True),
    ("Fingerling sales", "পোনা বিক্রি", I, B, [], False),
    ("Other income", "অন্যান্য আয়", I, B, [], False),
    ("Groceries (bazar)", "বাজার", E, H, [], False),
    ("Utilities", "বিল (বিদ্যুৎ, গ্যাস, পানি)", E, H, [], False),
    ("House rent", "বাসা ভাড়া", E, H, [], False),
    ("Medical", "চিকিৎসা", E, H, [], False),
    ("Children", "সন্তান", E, H, [("School fees", "স্কুলের বেতন"), ("Tuition", "প্রাইভেট / টিউশন"), ("Books", "বই-খাতা"), ("Clothing", "জামাকাপড়")], False),
]


def seed_categories(business):
    added = 0
    for order, (name, name_bn, type_, scope, children, system) in enumerate(DEFAULT_CATEGORIES, 1):
        parent = Category.all_objects.filter(business=business, type=type_, scope=scope, parent=None, name__iexact=name).first()
        if parent is None:
            parent = Category.all_objects.create(business=business, name=name, name_bn=name_bn, type=type_, scope=scope,
                                                 is_system=system, order=order)
            added += 1
        for c_order, (child, child_bn) in enumerate(children, 1):
            if not Category.all_objects.filter(business=business, parent=parent, name__iexact=child).exists():
                Category.all_objects.create(business=business, name=child, name_bn=child_bn, type=type_, scope=scope,
                                            parent=parent, order=c_order)
                added += 1
    return added


def seed_accounts(business):
    if Account.all_objects.filter(business=business).exists():
        return 0
    Account.all_objects.create(business=business, name="Cash", kind=AccountKind.CASH, is_default=True, opening_date=date.today())
    return 1
