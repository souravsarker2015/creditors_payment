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

# Usual selling size in grams per fish, for the harvest forecast.
MARKET_SIZE_G = {
    "Rui": 1000, "Katla": 1500, "Mrigal": 800, "Kalibaus": 800, "Silver carp": 1000, "Grass carp": 1500,
    "Common carp": 1000, "Bighead carp": 1500, "Pangas": 1000, "Tilapia": 250, "Koi": 100, "Shing": 60,
    "Magur": 150, "Pabda": 40, "Gulsha": 40, "Sarpunti": 200, "Golda prawn": 60, "Bagda shrimp": 40,
}


# A rough, common stocking guide in Bangladesh (fingerlings per decimal of water).
# Carps are usually raised together (about 30–40 per decimal in all), so each
# carp's figure is its usual share of that mix; the others are raised alone.
# Every farm can change these under Fish species.
STOCK_PER_DECIMAL = {
    "Rui": 10, "Katla": 4, "Mrigal": 8, "Kalibaus": 3, "Silver carp": 6, "Grass carp": 3, "Common carp": 4, "Bighead carp": 2,
    "Pangas": 120, "Tilapia": 150, "Koi": 400, "Shing": 400, "Magur": 200, "Pabda": 250, "Gulsha": 300, "Sarpunti": 60,
    "Golda prawn": 40, "Bagda shrimp": 60,
}


def seed_species(business):
    have = {n.lower() for n in Species.all_objects.filter(business=business).values_list("name", flat=True)}
    kg = Unit.objects.filter(business=business, symbol="kg").first()
    added = 0
    for order, (name, name_bn, sci) in enumerate(DEFAULT_SPECIES, 1):
        if name.lower() in have:
            continue
        Species.all_objects.create(business=business, name=name, name_bn=name_bn, scientific_name=sci,
                                   default_unit=kg, market_size_g=MARKET_SIZE_G.get(name),
                                   stock_per_decimal=STOCK_PER_DECIMAL.get(name), color=COLORS[order % len(COLORS)], order=order)
        added += 1
    return added
