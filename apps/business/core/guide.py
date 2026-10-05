"""The farm's workflow, as data: what you do, in what order, and what it feeds.

One description of the system, shown three ways on the guide page: a flow map,
stage-by-stage cards, and a "where does a number come from" list. Changing the
system means changing it here too.
"""
from dataclasses import dataclass, field

from django.urls import NoReverseMatch, reverse
from django.utils.translation import gettext_lazy as _


@dataclass
class Step:
    key: str
    title: str
    what: str                       # what you do
    url_name: str = ""
    cap: str = ""                   # only shown to people who may do it
    feeds: tuple = ()               # keys of the steps this one feeds
    icon: str = "list"
    note: str = ""                  # the rule worth knowing

    def url(self):
        if not self.url_name:
            return ""
        try:
            return reverse(f"business:{self.url_name}")
        except NoReverseMatch:      # an app that isn't installed, or a renamed route
            return ""


@dataclass
class Stage:
    key: str
    number: int
    title: str
    text: str
    tone: str                       # accent | info | good | warn | gold
    steps: list = field(default_factory=list)


STAGES = [
    Stage("setup", 1, _("Set the farm up once"),
          _("Lists everything else is built on. Common ones are filled in for you; change them any time."), "accent", [
              Step("ponds", _("Ponds"), _("Every pond or gher: name, size, and whether it's leased."),
                   "ponds", "manage_settings", ("cycle",), "fish",
                   _("Size is what makes “profit per decimal” possible, so different ponds can be compared.")),
              Step("species", _("Fish species"), _("The fish you raise, with their Bangla names."),
                   "species", "manage_settings", ("stocking", "harvest", "sale"), "fish"),
              Step("feed_products", _("Feed products"), _("Each feed with its bag size and usual price."),
                   "feed_products", "manage_settings", ("feed_buy",), "banknotes"),
              Step("parties", _("Suppliers & buyers"), _("Who you buy from and sell to, with any old balance."),
                   "suppliers", "manage_settings", ("feed_buy", "sale", "baki"), "truck"),
              Step("markets", _("Markets & deductions"), _("Where you sell, and what each aarot takes off a sale."),
                   "markets", "manage_settings", ("sale",), "cart",
                   _("Set the usual commission, labour and khajna once; every sale there starts with them.")),
              Step("accounts", _("Accounts & categories"), _("Cash, bank and bKash, and what to call your income and costs."),
                   "accounts", "view_finance", ("money", "sale", "feed_buy"), "wallet"),
          ]),
    Stage("grow", 2, _("Raise the fish"),
          _("A cycle is one round of farming in a pond. Everything below is recorded inside it."), "info", [
              Step("cycle", _("Start a cycle"), _("Open the pond and start a cycle when you release fingerlings."),
                   "ponds", "enter_data", ("stocking", "feeding", "water", "growth", "harvest"), "fish",
                   _("The pond is marked “Fish in it” by itself, and “Empty” when you finish the cycle.")),
              Step("stocking", _("Release fingerlings"), _("How many, from whom, and what they cost."),
                   "", "enter_data", ("cost",), "fish",
                   _("Pay part now and the rest becomes Baki owed to that supplier.")),
              Step("feed_buy", _("Buy feed"), _("Copy the dealer's memo: feeds, bags and rate."),
                   "feed_purchases_add", "enter_data", ("stock", "baki"), "truck",
                   _("Stock goes up straight away. What you didn't pay becomes Baki.")),
              Step("feeding", _("Feed the ponds"), _("What each pond ate today — several ponds in one go."),
                   "feed_usage_bulk", "enter_data", ("stock", "cost", "fcr"), "banknotes",
                   _("Feed becomes a cost when it's eaten, not when it's bought.")),
              Step("feedplan", _("Feed plan"), _("How much each pond should get today, and how long the feed lasts."),
                   "feed_plan", "", ("feeding",), "banknotes",
                   _("Fish weight × a rate for their size, cut back in cold water or low oxygen.")),
              Step("water", _("Test the water"), _("Oxygen, pH, ammonia… against your own alert levels."),
                   "", "enter_data", ("alerts",), "beaker",
                   _("A reading outside your levels warns you on the cycle page and the home page.")),
              Step("care", _("Lime, medicine & care"), _("What went into each pond, how much, and why — with a dose calculator."),
                   "", "enter_data", ("cost", "alerts", "calendar"), "dropper",
                   _("A medicine's waiting period warns you before fish from that pond are sold.")),
              Step("growth", _("Weigh and count losses"), _("A sample weighing every 2–3 weeks, and any deaths."),
                   "", "enter_data", ("fcr", "alerts"), "scale",
                   _("Sample weights are how the app estimates the fish in the pond, the FCR and “if you sell now”.")),
          ]),
    Stage("sell", 3, _("Harvest and sell"),
          _("Fish out of the pond, then the money for it. They're two separate records."), "good", [
              Step("harvest", _("Record the harvest"), _("How much fish came out, by weight or count."),
                   "", "enter_data", ("sale",), "cart",
                   _("Tap “Sell” on a harvest and the sale starts filled in.")),
              Step("sale", _("Record the sale"), _("The fish, quantity and rate from the aarot's memo."),
                   "sale_add", "enter_data", ("baki", "money", "cycle_profit"), "cart",
                   _("Market deductions come in by themselves; what the buyer didn't pay becomes Baki.")),
              Step("prices", _("Fish prices"), _("What each fish is fetching: your own sale rates and prices you note at the aarot."),
                   "prices", "", (), "arrow-up",
                   _("Every rate becomes a price per kg, so mon and kg rates compare directly.")),
              Step("baki", _("Baki (dues)"), _("Who owes you and whom you owe, worked out for you."),
                   "dues", "view_finance", ("money",), "book",
                   _("Record a payment and it settles the oldest bill first, unless you pick one.")),
          ]),
    Stage("money", 4, _("Keep the money straight"),
          _("Everything else that comes in or goes out, and what you plan to spend."), "gold", [
              Step("money", _("Money in & out"), _("Labour, medicine, lime, electricity, household costs…"),
                   "transactions", "view_finance", ("cost", "profit"), "wallet",
                   _("Put a cost on a pond's cycle and it counts in that pond's profit.")),
              Step("staff", _("Staff & wages"), _("A work sheet for daily workers, a salary sheet for monthly staff, and what you've paid."),
                   "staff", "view_finance", ("cost", "profit"), "users",
                   _("Wages are a cost when they're earned; an advance is simply taken off later pay.")),
              Step("lease", _("Pond lease"), _("What you pay the owners of leased ponds, and what's still due."),
                   "ponds", "view_finance", ("cost", "profit"), "calendar",
                   _("Each cycle carries its share of the lease, by the days it ran.")),
              Step("equipment", _("Equipment"), _("Aerators, pumps and nets: their price, repairs and services."),
                   "equipment", "", ("profit", "alerts", "calendar"), "cog",
                   _("A service due or a machine that needs repair shows on today's list.")),
              Step("loans", _("Loans"), _("Instalments, interest and what's still owed."),
                   "loans", "view_finance", ("profit", "calendar"), "banknotes",
                   _("Only interest and charges are a cost; repaying the loan itself is not.")),
              Step("budget", _("Budget & regular bills"), _("What you plan to spend, and bills that come back."),
                   "budget", "view_finance", ("calendar",), "tag"),
          ]),
    Stage("see", 5, _("See how you're doing"),
          _("Nothing here is typed in: every figure is worked out from the records above."), "warn", [
              Step("cycle_profit", _("Pond & cycle profit"), _("What each cycle cost, sold and made."),
                   "reports", "view_reports", (), "fish"),
              Step("fcr", _("FCR & growth"), _("Feed used for each kg the fish grew."),
                   "", "view_reports", (), "scale"),
              Step("stock", _("Feed stock"), _("Bought minus eaten, and what it's worth."),
                   "feed_stock", "", (), "banknotes"),
              Step("profit", _("Income & expenses"), _("What came in, what went out, what's left."),
                   "statement", "view_reports", (), "scale"),
              Step("alerts", _("Today on the farm"), _("Water problems, deaths, unfed ponds, weighings due."),
                   "home", "", (), "alert"),
              Step("calendar", _("Calendar"), _("Everything on its day, in English and Bangla dates."),
                   "calendar", "", (), "calendar"),
              Step("cost", _("Costs add up"), _("Fingerlings, feed eaten and pond costs together."),
                   "dashboard", "view_reports", (), "scale"),
          ]),
]

# "Where does this number come from?" — the questions farmers actually ask.
ANSWERS = [
    (_("Profit of a cycle"), _("Fish sold (after market deductions) − fingerlings − feed eaten − lime & medicine − wages, its share of the pond lease and other costs put on that cycle."),
     ("sale", "stocking", "feeding", "care", "staff", "lease", "money")),
    (_("Fish in the pond"), _("Fingerlings released − deaths recorded − fish harvested by count."), ("stocking", "growth", "harvest")),
    (_("Weight in the pond"), _("Fish in the pond × their latest sample weight."), ("growth",)),
    (_("FCR"), _("Feed eaten ÷ weight the fish gained (harvest − fingerling weight). Lower is better."), ("feeding", "growth", "harvest")),
    (_("Feed cost of a pond"), _("Feed eaten there × the average price per kg you paid for that feed."), ("feed_buy", "feeding")),
    (_("Baki of a person"), _("Their unpaid bills (sales, feed, fingerlings) − what they've paid, oldest first."), ("sale", "feed_buy", "baki")),
    (_("Money in an account"), _("Opening balance + everything in − everything out of that account."), ("sale", "baki", "money")),
    (_("Farm profit"), _("Fish sales + other farm income − feed eaten − fingerlings − lime & medicine − staff wages − pond lease − equipment & repairs − farm costs − loan interest."), ("sale", "feeding", "care", "staff", "lease", "equipment", "money", "loans")),
    (_("What a worker is owed"), _("Their opening balance + days worked, salaries and bonuses − deductions − what you've paid them. Below zero means they hold an advance."), ("staff",)),
]


def stages_for(can_do):
    """The stages with only the steps this person may see, and their links."""
    out = []
    for stage in STAGES:
        steps = []
        for s in stage.steps:
            if s.cap and not can_do(s.cap):
                continue
            steps.append({"key": s.key, "title": s.title, "what": s.what, "note": s.note, "icon": s.icon,
                          "url": s.url(), "feeds": s.feeds})
        if steps:
            out.append({"key": stage.key, "number": stage.number, "title": stage.title, "text": stage.text,
                        "tone": stage.tone, "steps": steps})
    return out


def answers_for(titles):
    """The "where does it come from" list, with each step's title for the chips."""
    return [{"question": q, "how": how, "from": [titles[k] for k in keys if k in titles]} for q, how, keys in ANSWERS]


def step_titles():
    return {s.key: s.title for stage in STAGES for s in stage.steps}
