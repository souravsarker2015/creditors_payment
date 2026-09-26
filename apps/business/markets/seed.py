from .models import DeductionMethod, DeductionType

DEFAULT_DEDUCTIONS = [
    ("Aarot commission", "আড়তদারি কমিশন", DeductionMethod.PERCENT),
    ("Labour", "শ্রমিক / কুলি", DeductionMethod.PER_UNIT),
    ("Transport", "পরিবহন", DeductionMethod.FIXED),
    ("Toll / khajna", "খাজনা", DeductionMethod.FIXED),
    ("Ice", "বরফ", DeductionMethod.FIXED),
    ("Basket / drum", "ঝুড়ি / ড্রাম", DeductionMethod.FIXED),
    ("Other", "অন্যান্য", DeductionMethod.FIXED),
]


def seed_deduction_types(business):
    have = {n.lower() for n in DeductionType.all_objects.filter(business=business).values_list("name", flat=True)}
    added = 0
    for order, (name, name_bn, method) in enumerate(DEFAULT_DEDUCTIONS):
        if name.lower() not in have:
            DeductionType.all_objects.create(business=business, name=name, name_bn=name_bn, method=method, order=order)
            added += 1
    return added
