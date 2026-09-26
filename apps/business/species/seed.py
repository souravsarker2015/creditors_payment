from apps.business.core.models import Unit

from .models import COLORS, Species

# English, Bangla, scientific name
DEFAULT_SPECIES = [
    ("Rui", "রুই", "Labeo rohita"),
    ("Katla", "কাতলা", "Catla catla"),
    ("Mrigal", "মৃগেল", "Cirrhinus cirrhosus"),
    ("Kalibaus", "কালিবাউশ", "Labeo calbasu"),
    ("Silver carp", "সিলভার কার্প", "Hypophthalmichthys molitrix"),
    ("Grass carp", "গ্রাস কার্প", "Ctenopharyngodon idella"),
    ("Common carp", "কমন কার্প", "Cyprinus carpio"),
    ("Bighead carp", "বিগহেড কার্প", "Hypophthalmichthys nobilis"),
    ("Pangas", "পাঙ্গাস", "Pangasianodon hypophthalmus"),
    ("Tilapia", "তেলাপিয়া", "Oreochromis niloticus"),
    ("Koi", "কই", "Anabas testudineus"),
    ("Shing", "শিং", "Heteropneustes fossilis"),
    ("Magur", "মাগুর", "Clarias batrachus"),
    ("Pabda", "পাবদা", "Ompok pabda"),
    ("Gulsha", "গুলশা", "Mystus cavasius"),
    ("Sarpunti", "সরপুঁটি", "Barbonymus gonionotus"),
    ("Golda prawn", "গলদা চিংড়ি", "Macrobrachium rosenbergii"),
    ("Bagda shrimp", "বাগদা চিংড়ি", "Penaeus monodon"),
]


def seed_species(business):
    have = {n.lower() for n in Species.all_objects.filter(business=business).values_list("name", flat=True)}
    kg = Unit.objects.filter(business=business, symbol="kg").first()
    added = 0
    for order, (name, name_bn, sci) in enumerate(DEFAULT_SPECIES, 1):
        if name.lower() in have:
            continue
        Species.all_objects.create(business=business, name=name, name_bn=name_bn, scientific_name=sci,
                                   default_unit=kg, color=COLORS[order % len(COLORS)], order=order)
        added += 1
    return added
