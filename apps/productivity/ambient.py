"""Background sound: what can be mixed (made in the browser by static/js/ambient.js — nothing to download, works offline)
and the ready-made mixes, each for what it suits:

- Steady sound with no words in it (brown noise, rain, a stream) covers the noises that pull attention away — a door,
  a voice, traffic — so it suits focus. Brown noise is the deepest and least tiring; many people with ADHD like it best.
- Nature sounds (water, birds, wind) calm the body down and rest tired attention — they suit breaks and reading.
- A fire and rain feel cosy: low and slow, they suit reading for a long time.
- Binaural beats need headphones; how much they help differs a lot from person to person, so they're one choice among many.

A mix is "rain:60,fire:30": each sound at its own level (WorkSettings.focus_mix / break_mix / reading_mix)."""
from django.utils.translation import gettext as _

# (id, icon, name) — in the order the mixer shows them; the ids are the ones static/js/ambient.js knows how to make
LAYERS = (
    ("rain", "🌧️", "Rain"), ("thunder", "⛈️", "Thunder"), ("waves", "🌊", "Sea waves"), ("stream", "🏞️", "Stream"),
    ("wind", "🍃", "Wind"), ("fire", "🔥", "Fireplace"), ("birds", "🐦", "Birds"), ("night", "🦗", "Night crickets"),
    ("brown", "🟤", "Brown noise"), ("pink", "🌸", "Pink noise"), ("white", "⚪", "White noise"), ("binaural", "🎧", "Binaural beats"),
)

# (id, name, mix, what it suits, why) — the mixer shows the ones for what it's setting first
PRESETS = (
    ("deep", "Deep focus", "brown:70", ("focus", "reading"), "Deep, steady, covers voices and noise"),
    ("rain", "Rainy day", "rain:70,brown:20", ("focus", "reading"), "The favourite for working and studying"),
    ("fireside", "Fireside", "fire:60,rain:35", ("reading",), "Cosy and slow — for long reading"),
    ("sea", "Seaside", "waves:70,wind:15", ("break", "reading", "focus"), "Slow waves calm your breathing"),
    ("forest", "Forest stream", "stream:55,birds:35", ("break", "reading", "focus"), "Nature rests tired attention"),
    ("storm", "Storm", "rain:75,thunder:45,wind:20", ("focus",), "Heavy rain: shuts the world out"),
    ("night", "Quiet night", "night:45,wind:15", ("break", "reading"), "Soft and still"),
    ("pink", "Pink noise", "pink:60", ("focus",), "Softer than white noise"),
    ("beats", "Study beats", "binaural:45,brown:30", ("focus",), "Use headphones"),
)


def catalogue():
    """For the page (Work.cfg.ambient): the sounds and the ready-made mixes, in the person's language."""
    return {
        "layers": [{"id": i, "icon": icon, "name": _(name)} for i, icon, name in LAYERS],
        "presets": [{"id": i, "name": _(name), "mix": mix, "for": list(good_for), "why": _(why)} for i, name, mix, good_for, why in PRESETS],
    }


def config(s):
    """What static/js/ambient.js goes by: the three mixes, the volume, and whether timers and the stopwatch bring the sound too."""
    return {"mixes": {"focus": s.focus_mix, "break": s.break_mix, "reading": s.reading_mix}, "mixVolume": s.mix_volume,
            "withTimers": s.sound_with_timers, "ambient": catalogue()}
