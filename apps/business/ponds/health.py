"""Fish health: the problems Bangladeshi pond farmers meet most, how to tell
them apart, and safe first steps. Plain guidance, not a prescription: a
medicine's dose and waiting period come from its label and the local fisheries
office."""
from dataclasses import dataclass

from django.utils.translation import gettext_lazy as _


@dataclass(frozen=True)
class Problem:
    key: str
    name: str
    signs: str
    why: str
    do: tuple
    when: str = ""        # season or time it's most common
    urgent: bool = False


PROBLEMS = [
    Problem("oxygen", _("Low oxygen"),
            _("Fish gasp at the surface in the early morning, crowd near the inlet, and the big ones die first."),
            _("Cloudy, hot, still weather; too many fish; thick green water; rotting feed on the bottom."),
            (_("Run the aerator or pump in fresh water at once, and beat the water surface."),
             _("Don't feed until the fish behave normally again."),
             _("Test the oxygen just before sunrise for the next few days."),
             _("If it keeps happening, the pond holds more fish than its water can carry: harvest some or thin it out.")),
            _("Cloudy and hot days, before dawn"), urgent=True),
    Problem("ulcer", _("Red sores / ulcer disease (EUS)"),
            _("Red spots that turn into open sores on the body and head; fish swim slowly and stop eating."),
            _("Cold water in winter, a sudden drop in temperature, dirty or acidic water."),
            (_("Spread lime (about 1 kg per decimal) to settle and freshen the water."),
             _("Take out sick and dead fish, and keep netting and handling to a minimum."),
             _("Ask the upazila fisheries office before using any medicine, and note its waiting period here.")),
            _("November to February")),
    Problem("gills", _("Gill rot"),
            _("Gills pale, grey or rotting; fish breathe fast and hang near the surface."),
            _("A dirty bottom, too much feed, high ammonia."),
            (_("Change part of the water and cut the feed for a few days."),
             _("Lime the pond; zeolite helps take up ammonia."),
             _("Test the ammonia and the oxygen."))),
    Problem("whitespot", _("White spots"),
            _("Tiny white grains on the skin and fins; fish rub against the sides and bottom."),
            _("A small parasite that spreads in cool, crowded water."),
            (_("Raise water exchange and lower crowding."),
             _("A salt bath or a pond treatment from the dealer helps — follow the label for the dose."))),
    Problem("lice", _("Fish lice (Argulus)"),
            _("Small flat lice visible on the body, red spots where they bite; fish jump and rub."),
            _("Lice that build up in ponds not dried between cycles."),
            (_("Use an approved lice treatment from a reliable dealer, at the label's dose."),
             _("Dry the pond and lime the bottom before the next cycle."))),
    Problem("dropsy", _("Swollen belly (dropsy)"),
            _("The belly swells, scales stand out like a pine cone, eyes may bulge."),
            _("A bacterial infection, usually in stressed fish in poor water or on stale feed."),
            (_("Take sick fish out at once so it doesn't spread."),
             _("Improve the water and use fresh feed, stored dry."),
             _("Ask the fisheries office before giving any antibiotic."))),
    Problem("finrot", _("Fin and tail rot"),
            _("Fin and tail edges ragged, white or bloody."),
            _("Injuries from netting or crowding, then infection in dirty water."),
            (_("Handle fish gently and don't over-stock."),
             _("Clean water and lime usually let them heal."))),
    Problem("water", _("Bad water / ammonia"),
            _("Fish are slow and don't eat; the water smells or turns dark; deaths after feeding."),
            _("Too much feed or manure, a dirty bottom, algae dying off."),
            (_("Stop feeding for a day or two."),
             _("Change some water; probiotics or zeolite help clean the bottom."),
             _("Then feed by the feed plan, not more.")), urgent=True),
]

PREVENT = (
    _("Dry the pond, remove the black mud and lime it before stocking."),
    _("Buy healthy, lively fingerlings from a known hatchery, and don't over-stock."),
    _("Feed by the plan, and less on cloudy, cold or very hot days."),
    _("Test the water every week — oxygen just before sunrise."),
    _("Take dead fish out every day and note them, so trouble shows early."),
    _("Wait out a medicine's waiting period before you sell fish from that pond."),
)
