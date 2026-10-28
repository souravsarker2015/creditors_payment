"""The job search, as Huntr or Teal keep it, joined up with the rest of Productivity:

- applications on a board by stage (Wishlist → Applied → Screening → Interviewing → Offer), each with
  its interview rounds, its next step and the date for it (Today shows it when the day comes), and a
  nudge when one has been quiet for two weeks;
- the funnel: how many got an answer, an interview, an offer — where the search leaks;
- what a job asks for (the skills named in its description) next to what the question bank has, and
  the bank's questions asked at that company;
- the questions asked in a round go into the bank (topic "Asked in interviews"), for spaced practice;
- STAR stories (Story) by what they show, the common behavioural questions each one answers, and
  which of those have no story yet."""
import re
from datetime import timedelta

from django.db.models import Count, Max, Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .models import OPEN_STAGES, JobApplication, JobRound, JobStage, PrepTopic, Question, QuestionKind, Story

QUIET_DAYS = 14             # applied this long ago with no news: time to follow up
SOON_DAYS = 7               # interviews this far ahead are on Today
BANK_TOPIC = "Asked in interviews"

# ── The funnel ────────────────────────────────────────────────────────────
def funnel(user):
    """{"applied", "answered", "interviews", "offers", "answer_rate", "interview_rate", "offer_rate", "by_stage"}."""
    apps = JobApplication.objects.filter(owner=user)
    by_stage = dict(apps.values_list("stage").annotate(n=Count("pk")))
    sent = apps.exclude(stage=JobStage.WISHLIST)
    with_rounds = set(JobRound.objects.filter(application__owner=user).values_list("application_id", flat=True))
    applied = sent.count()
    answered = sent.filter(Q(stage__in=(JobStage.SCREEN, JobStage.INTERVIEW, JobStage.OFFER, JobStage.ACCEPTED)) | Q(pk__in=with_rounds)).count()
    interviews = sent.filter(Q(stage__in=(JobStage.INTERVIEW, JobStage.OFFER, JobStage.ACCEPTED)) | Q(pk__in=with_rounds)).count()
    offers = sent.filter(Q(stage__in=(JobStage.OFFER, JobStage.ACCEPTED)) | Q(closed_reason__icontains="offer")).count()

    def pct(n):
        return round(100 * n / applied) if applied else None
    return {"applied": applied, "answered": answered, "interviews": interviews, "offers": offers,
            "answer_rate": pct(answered), "interview_rate": pct(interviews), "offer_rate": pct(offers),
            "by_stage": {s: by_stage.get(s, 0) for s in JobStage.values}}


# ── What's due ────────────────────────────────────────────────────────────
def coming_up(user, today=None, days=SOON_DAYS):
    """Interviews in the next days, next steps due (today or late), and applications gone quiet."""
    today = today or timezone.localdate()
    now = timezone.now()
    rounds = list(JobRound.objects.filter(application__owner=user, at__gte=now - timedelta(hours=2),
                                          at__lt=now + timedelta(days=days)).select_related("application").order_by("at"))
    due = list(JobApplication.objects.filter(owner=user, next_on__lte=today).exclude(stage__in=(JobStage.ACCEPTED, JobStage.CLOSED))
               .order_by("next_on", "pk"))
    quiet = [a for a in JobApplication.objects.filter(owner=user, stage=JobStage.APPLIED, next_on__isnull=True).order_by("stage_changed_at")
             if a.days_quiet(today) >= QUIET_DAYS][:5]
    return {"rounds": rounds, "due": due, "quiet": quiet, "count": len(rounds) + len(due) + len(quiet)}


# ── Moving along ──────────────────────────────────────────────────────────
def move(app, stage, order=None):
    """To another stage (a drag on the board): the date it moved, and the day it was sent."""
    if stage not in JobStage.values:
        return False
    if stage != app.stage:
        app.stage, app.stage_changed_at = stage, timezone.now()
        if stage != JobStage.WISHLIST and not app.applied_on:
            app.applied_on = timezone.localdate()
    if order is not None:
        app.order = order
    app.save()
    return True


def next_order(user, stage):
    top = JobApplication.objects.filter(owner=user, stage=stage).aggregate(m=Max("order"))["m"]
    return (top or 0) + 1


# ── What the job asks for, next to what's prepared ────────────────────────
# (how a skill is written in a job description → the name it goes by)
SKILLS = {
    "python": "Python", "django": "Django", "flask": "Flask", "fastapi": "FastAPI", "java": "Java", "spring": "Spring",
    "kotlin": "Kotlin", "golang": "Go", "go": "Go", "rust": "Rust", "c#": "C#", ".net": ".NET", "c++": "C++", "php": "PHP",
    "laravel": "Laravel", "ruby": "Ruby", "rails": "Rails", "javascript": "JavaScript", "typescript": "TypeScript",
    "node": "Node.js", "node.js": "Node.js", "react": "React", "next.js": "Next.js", "vue": "Vue", "angular": "Angular",
    "html": "HTML", "css": "CSS", "tailwind": "Tailwind", "sql": "SQL", "postgresql": "PostgreSQL", "postgres": "PostgreSQL",
    "mysql": "MySQL", "oracle": "Oracle", "mongodb": "MongoDB", "redis": "Redis", "elasticsearch": "Elasticsearch",
    "kafka": "Kafka", "rabbitmq": "RabbitMQ", "graphql": "GraphQL", "rest": "REST APIs", "grpc": "gRPC",
    "microservices": "Microservices", "aws": "AWS", "azure": "Azure", "gcp": "GCP", "docker": "Docker",
    "kubernetes": "Kubernetes", "k8s": "Kubernetes", "terraform": "Terraform", "ci/cd": "CI/CD", "jenkins": "CI/CD",
    "github actions": "CI/CD", "linux": "Linux", "git": "Git", "system design": "System design",
    "distributed systems": "Distributed systems", "data structures": "Data structures & algorithms",
    "algorithms": "Data structures & algorithms", "oop": "OOP", "design patterns": "Design patterns",
    "testing": "Testing", "tdd": "Testing", "pytest": "Testing", "machine learning": "Machine learning",
    "spark": "Spark", "airflow": "Airflow", "android": "Android", "ios": "iOS", "swift": "Swift", "flutter": "Flutter",
    "security": "Security", "networking": "Networking", "agile": "Agile", "scrum": "Agile",
}
_SKILL_RX = re.compile(r"(?<![\w.#+])(" + "|".join(sorted((re.escape(k) for k in SKILLS), key=len, reverse=True)) + r")(?![\w#+])", re.I)


def skills_in(text):
    """The skills a job description names, each once, in the order they come."""
    return list(dict.fromkeys(SKILLS[m.group(1).lower()] for m in _SKILL_RX.finditer(text or "")))


# what else a skill is called in a question bank (its topic's name, or the question's words)
SKILL_ALIASES = {
    "Data structures & algorithms": ("algorithm", "data structure", "DSA", "leetcode"),
    "System design": ("system design", "scalab", "architecture"),
    "Distributed systems": ("distributed", "consensus", "replication"),
    "REST APIs": ("REST", "HTTP API"), "Node.js": ("Node",), "PostgreSQL": ("Postgres",), "Kubernetes": ("k8s",),
    "CI/CD": ("CI/CD", "pipeline", "GitHub Actions"), "Testing": ("test",), "Machine learning": ("ML ", "model training"),
}


def skill_readiness(user, skills):
    """Each skill with how many bank questions touch it — by the topic's name or the question's text.
    A short name ("Go", "Git", "AWS") must be a word of its own: "Go" isn't in "Google" or "algorithms"."""
    out = []
    for s in skills:
        words = (s,) + SKILL_ALIASES.get(s, ())
        cond = Q()
        for word in words:
            cond |= Q(topic__name__icontains=word) | Q(prompt__icontains=word)
        qs = Question.objects.filter(owner=user).filter(cond)
        if len(s) <= 3:
            rx = re.compile(r"(?<![\w#+.])(?:" + "|".join(re.escape(w) for w in words) + r")(?![\w#+])", re.I)
            n = sum(1 for topic, prompt in qs.values_list("topic__name", "prompt") if rx.search(topic) or rx.search(prompt))
        else:
            n = qs.count()
        out.append({"skill": s, "questions": n})
    return out


def company_questions(user, company):
    """Bank questions known to be asked at this company."""
    name = company.strip()
    return Question.objects.filter(owner=user, companies__icontains=name).select_related("topic") if len(name) >= 2 else Question.objects.none()


def to_bank(rnd):
    """A round's questions → the question bank (topic "Asked in interviews"), marked with the company.
    Returns how many were added (one already there isn't added twice)."""
    user, company = rnd.application.owner, rnd.application.company
    lines = rnd.question_list
    if not lines:
        return 0
    topic = PrepTopic.objects.filter(owner=user, name=BANK_TOPIC).first() or PrepTopic.objects.create(owner=user, name=str(BANK_TOPIC), code="ASK")
    have = set(Question.objects.filter(owner=user, topic=topic).values_list("prompt", flat=True))
    kind = {"technical": QuestionKind.CODE, "design": QuestionKind.LONG}.get(rnd.kind, QuestionKind.SHORT)
    start = (Question.objects.filter(topic=topic).aggregate(m=Max("order"))["m"] or 0) + 1
    made = 0
    for line in lines:
        if line in have:
            continue
        Question.objects.create(owner=user, topic=topic, prompt=line, kind=kind,
                                companies=company[:200], order=start + made, notes=f"{rnd.get_kind_display()} · {company}")
        have.add(line)
        made += 1
    return made


# ── STAR stories ──────────────────────────────────────────────────────────
# What a behavioural question is really after, and the questions that ask for it
COMPETENCIES = {
    "ownership": (_("Ownership"), [_("Tell me about a time you took on something nobody asked you to."),
                                   _("Describe a project you drove from start to finish.")]),
    "impact": (_("Impact"), [_("What's the work you're proudest of, and why?"),
                             _("Tell me about a time you improved something measurably.")]),
    "leadership": (_("Leadership"), [_("Tell me about a time you led a team or a project."),
                                     _("Describe a time you had to motivate others.")]),
    "conflict": (_("Conflict"), [_("Tell me about a disagreement with a colleague. How did you resolve it?"),
                                 _("Describe a time you pushed back on a manager's decision.")]),
    "failure": (_("Failure"), [_("Tell me about a time you failed. What did you learn?"),
                               _("Describe a mistake you made in production.")]),
    "ambiguity": (_("Ambiguity"), [_("Tell me about a time you had to act without clear requirements."),
                                   _("Describe a decision you made with incomplete information.")]),
    "deadline": (_("Pressure"), [_("Tell me about a time you had a tight deadline."),
                                 _("Describe a time you had to juggle competing priorities.")]),
    "technical": (_("Hard problem"), [_("Tell me about the hardest bug you've fixed."),
                                      _("Describe a technical decision you made and its trade-offs.")]),
    "customer": (_("Customer focus"), [_("Tell me about a time you went out of your way for a user or customer."),
                                       _("Describe a time you changed a plan because of feedback.")]),
    "teamwork": (_("Teamwork"), [_("Tell me about a time you helped a teammate succeed."),
                                 _("Describe working with a difficult person.")]),
    "learning": (_("Learning"), [_("Tell me about a time you learnt something new quickly."),
                                 _("Describe feedback you received and what you changed.")]),
    "mentoring": (_("Mentoring"), [_("Tell me about a time you mentored or taught someone."),
                                   _("Describe how you've raised the bar for your team.")]),
}


def coverage(user):
    """Each competency with its stories: [{"key", "label", "stories": [...]}] — the empty ones are the gaps."""
    stories = list(Story.objects.filter(owner=user))
    return [{"key": k, "label": label, "stories": [s for s in stories if k in (s.competencies or [])]} for k, (label, _qs) in COMPETENCIES.items()]


def practice_deck():
    """Every common question with what it's after: [{"q", "key", "label"}]."""
    return [{"q": str(q), "key": k, "label": str(label)} for k, (label, qs) in COMPETENCIES.items() for q in qs]


def open_count(user):
    return JobApplication.objects.filter(owner=user, stage__in=OPEN_STAGES).count()
