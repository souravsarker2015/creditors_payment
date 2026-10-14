"""Flashcards: when each card comes up again (spaced repetition), what is due
today, the numbers for the Flashcards page, and turning text, notes and mind
maps into cards.

Scheduling is a small SM-2 (the method behind most flashcard apps). Every
answer is one of four buttons:

    1 Again  forgot it         → shown again in this session; a learnt card loses ease
    2 Hard   remembered slowly → a new card comes back later today; a learnt one waits a little longer than last time
    3 Good   remembered        → the wait grows by the card's ease (about 2.5×)
    4 Easy   knew it at once   → the wait grows faster, and the card gets easier
"""
import re
from datetime import datetime, time, timedelta

from django.db.models import Count, Min, Q
from django.utils import timezone
from django.utils.translation import gettext as _, ngettext

from .models import Card, CardReview, Deck

AGAIN, HARD, GOOD, EASY = 1, 2, 3, 4
RATINGS = (AGAIN, HARD, GOOD, EASY)
MIN_EASE, MAX_INTERVAL = 1.3, 36500
MATURE = 21              # days between reviews from which a card counts as "learnt"
SESSION_MAX = 200        # cards in one review session
MAX_FRONT, MAX_BACK = 2000, 10000


# ── Scheduling ──────────────────────────────────────────────────────────────
def _up(x):
    """Round half up (Python's round() goes to the even number: 2.5 → 2)."""
    return int(x + 0.5)


def next_state(card, rating):
    """(interval, ease, reps, lapses) after answering `card` with `rating`.
    An interval of 0 means "again today"."""
    ease, interval, reps, lapses = card.ease, card.interval, card.reps, card.lapses
    learning = card.last_reviewed is None or reps == 0
    if rating == AGAIN:
        if not learning:
            lapses += 1
            ease = max(MIN_EASE, ease - 0.2)
        return 0, ease, 0, lapses
    if learning:
        if rating == HARD:
            return 0, ease, 0, lapses
        if rating == GOOD:
            return 1, ease, 1, lapses
        return 4, ease + 0.15, 1, lapses
    if rating == HARD:
        interval, ease = max(interval + 1, _up(interval * 1.2)), max(MIN_EASE, ease - 0.15)
    elif rating == GOOD:
        interval = max(interval + 1, _up(interval * ease))
    else:
        interval, ease = max(interval + 2, _up(interval * ease * 1.3)), ease + 0.15
    return min(interval, MAX_INTERVAL), round(ease, 2), reps + 1, lapses


def answer(card, rating, now=None):
    """Record an answer: the card's next review moves, and the answer is kept for the numbers."""
    if rating not in RATINGS:
        raise ValueError("rating")
    now = now or timezone.now()
    before = {"interval": card.interval, "ease": card.ease, "reps": card.reps, "lapses": card.lapses, "due": card.due.isoformat(),
              "last_reviewed": card.last_reviewed.isoformat() if card.last_reviewed else None}
    interval, ease, reps, lapses = next_state(card, rating)
    card.interval, card.ease, card.reps, card.lapses = interval, ease, reps, lapses
    card.due = timezone.localdate(now) + timedelta(days=interval)
    card.last_reviewed = now
    card.save(update_fields=["interval", "ease", "reps", "lapses", "due", "last_reviewed", "updated_at"])
    card.review = CardReview.objects.create(owner=card.owner, card=card, rating=rating, interval=interval, reviewed_at=now, before=before)
    return card


def undo(review):
    """Take an answer back: the card's schedule goes back to how it was before it, and the answer is forgotten."""
    from django.utils.dateparse import parse_date, parse_datetime

    card, b = review.card, review.before or {}
    if not b:
        raise ValueError("nothing to undo")
    card.interval, card.ease, card.reps, card.lapses = b["interval"], b["ease"], b["reps"], b["lapses"]
    card.due = parse_date(b["due"]) or card.due
    card.last_reviewed = parse_datetime(b["last_reviewed"]) if b.get("last_reviewed") else None
    card.save(update_fields=["interval", "ease", "reps", "lapses", "due", "last_reviewed", "updated_at"])
    review.delete()
    return card


def wait_label(days):
    """How long until a card comes back, short: "now", "today", "3 days", "2 wk", "4 mo", "1.5 yr"."""
    if days <= 0:
        return _("today")
    if days < 14:
        return ngettext("%(n)d day", "%(n)d days", days) % {"n": days}
    if days < 60:
        return _("%(n)d wk") % {"n": round(days / 7)}
    if days < 365:
        return _("%(n)d mo") % {"n": round(days / 30)}
    years = days / 365
    return _("%(n)s yr") % {"n": f"{years:.1f}".rstrip("0").rstrip(".")}


def previews(card):
    """What each button would do to `card`: {rating: "3 days"}; Again always reads "now"."""
    out = {}
    for r in RATINGS:
        out[r] = _("now") if r == AGAIN else wait_label(next_state(card, r)[0])
    return out


# ── What's due ──────────────────────────────────────────────────────────────
def _day_start(today):
    return timezone.make_aware(datetime.combine(today, time.min))


def new_left(deck, today=None):
    """How many cards this deck may still show for the first time today."""
    today = today or timezone.localdate()
    started = (Card.objects.filter(deck=deck).annotate(first=Min("reviews__reviewed_at"))
               .filter(first__gte=_day_start(today)).count())
    return max(0, deck.new_per_day - started)


def due_cards(user, deck=None, today=None, limit=SESSION_MAX):
    """Cards for a review session: everything learnt that's due, then new
    cards up to each deck's daily allowance."""
    today = today or timezone.localdate()
    live = Card.objects.filter(owner=user, is_suspended=False, deck__is_archived=False).select_related("deck")
    if deck is not None:
        live = live.filter(deck=deck)
    review = list(live.filter(last_reviewed__isnull=False, due__lte=today).order_by("due", "pk")[:limit])
    fresh = []
    decks = [deck] if deck is not None else list(Deck.objects.filter(owner=user, is_archived=False))
    for dk in decks:
        room = min(new_left(dk, today), limit - len(review) - len(fresh))
        if room > 0:
            fresh += list(live.filter(deck=dk, last_reviewed__isnull=True).order_by("pk")[:room])
    # mix the new cards in among the reviews rather than leaving them all to the end
    out, step = [], max(1, len(review) // max(1, len(fresh))) if fresh else 0
    fresh_iter = iter(fresh)
    for i, c in enumerate(review):
        out.append(c)
        if step and (i + 1) % step == 0:
            nxt = next(fresh_iter, None)
            if nxt:
                out.append(nxt)
    out += list(fresh_iter)
    return out[:limit]


def deck_counts(user, today=None):
    """{deck id: {"due": learnt cards due, "new": new cards for today, "total", "learnt"}}."""
    today = today or timezone.localdate()
    rows = (Card.objects.filter(owner=user, is_suspended=False).values("deck")
            .annotate(due=Count("id", filter=Q(last_reviewed__isnull=False, due__lte=today)),
                      new=Count("id", filter=Q(last_reviewed__isnull=True)),
                      learnt=Count("id", filter=Q(interval__gte=MATURE)), total=Count("id")))
    out = {r["deck"]: dict(r) for r in rows}
    for dk in Deck.objects.filter(owner=user, pk__in=out):
        out[dk.pk]["new"] = min(out[dk.pk]["new"], new_left(dk, today))
    return out


def due_count(user, today=None):
    """Cards waiting for a review today, across every deck (for Today and the menu)."""
    counts = deck_counts(user, today)
    live = set(Deck.objects.filter(owner=user, is_archived=False).values_list("pk", flat=True))
    return sum(c["due"] + c["new"] for k, c in counts.items() if k in live)


def stats(user, today=None, days=91):
    """Numbers for the Flashcards page: today's answers, the streak, how much is remembered and a heatmap."""
    today = today or timezone.localdate()
    since = _day_start(today - timedelta(days=days - 1))
    per_day = {}
    for r in CardReview.objects.filter(owner=user, reviewed_at__gte=since).values_list("reviewed_at", flat=True):
        day = timezone.localdate(r)
        per_day[day] = per_day.get(day, 0) + 1
    streak, day = 0, today if per_day.get(today) else today - timedelta(days=1)
    while per_day.get(day):
        streak += 1
        day -= timedelta(days=1)
    month = CardReview.objects.filter(owner=user, reviewed_at__gte=_day_start(today - timedelta(days=29)))
    total = month.count()
    remembered = month.filter(rating__gt=AGAIN).count()
    cards = Card.objects.filter(owner=user)
    heat = [{"date": today - timedelta(days=i), "n": per_day.get(today - timedelta(days=i), 0)} for i in range(days - 1, -1, -1)]
    top = max([h["n"] for h in heat] + [1])
    for h in heat:
        h["level"] = 0 if not h["n"] else min(4, 1 + int(3 * h["n"] / top))
    return {
        "today": per_day.get(today, 0), "streak": streak,
        "retention": round(100 * remembered / total) if total else None,
        "cards": cards.count(), "learnt": cards.filter(interval__gte=MATURE).count(),
        "new": cards.filter(last_reviewed__isnull=True).count(), "heat": heat,
        "week": sum(per_day.get(today - timedelta(days=i), 0) for i in range(7)),
    }


def forecast(user, today=None, days=14):
    """How many learnt cards fall due on each of the next `days` days (overdue ones count for today)."""
    today = today or timezone.localdate()
    rows = dict(Card.objects.filter(owner=user, is_suspended=False, last_reviewed__isnull=False, deck__is_archived=False,
                                    due__lte=today + timedelta(days=days - 1))
                .values_list("due").annotate(n=Count("id")))
    out = []
    for i in range(days):
        day = today + timedelta(days=i)
        n = rows.get(day, 0) + (sum(v for k, v in rows.items() if k < today) if i == 0 else 0)
        out.append({"date": day, "n": n})
    top = max([o["n"] for o in out] + [1])
    for o in out:
        o["pct"] = round(100 * o["n"] / top)
    return out


# ── Making cards ────────────────────────────────────────────────────────────
PAIR = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)?(.+?)\s*(?:::|\t)\s*(.+?)\s*$")


def parse_pairs(text):
    """Cards from text, one a line: "question :: answer" (or the two split by a tab,
    as spreadsheets copy). Lines without either are left out."""
    out = []
    for line in (text or "").splitlines():
        m = PAIR.match(line)
        if m and m.group(1).strip() and m.group(2).strip():
            out.append((m.group(1).strip()[:MAX_FRONT], m.group(2).strip()[:MAX_BACK]))
    return out


def mindmap_pairs(data):
    """A mind map as cards: every idea with ideas under it asks for them.
    The front says where it sits ("Topic › Branch") so it makes sense alone."""
    out = []

    def walk(node, path):
        text = " ".join(str(node.get("text", "")).split())
        kids = [k for k in node.get("children") or [] if isinstance(k, dict) and str(k.get("text", "")).strip()]
        if kids and text:
            where = " › ".join(path)
            front = (f"_{where}_\n\n" if where else "") + f"**{text}**"
            back = "\n".join("- " + " ".join(str(k.get("text", "")).split()) for k in kids)
            out.append((front[:MAX_FRONT], back[:MAX_BACK]))
        for k in kids:
            walk(k, path + [text] if text else path)

    root = data.get("root") if isinstance(data, dict) else None
    if isinstance(root, dict):
        walk(root, [])
    return out


def add_cards(user, deck, pairs):
    """Put `pairs` into `deck`, leaving out any whose question is already there. Returns how many were added."""
    have = set(Card.objects.filter(deck=deck).values_list("front", flat=True))
    fresh, seen = [], set()
    for front, back in pairs:
        if front in have or front in seen:
            continue
        seen.add(front)
        fresh.append(Card(owner=user, deck=deck, front=front, back=back))
    Card.objects.bulk_create(fresh)
    return len(fresh)


def deck_named(user, name, **extra):
    """The person's deck called `name` (made if there isn't one)."""
    name = (name or _("My cards")).strip()[:120]
    deck = Deck.objects.filter(owner=user, name__iexact=name, is_archived=False).first()
    return deck or Deck.objects.create(owner=user, name=name, **extra)
